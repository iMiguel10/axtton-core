from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import Client
from app.core.db import workshop_transaction
from app.core.sessions import end_session
from app.services import portal_auth as portal_auth_service
from app.services.portal_auth import PortalClient, PortalSessionEndedError


@dataclass(frozen=True)
class PortalContext:
    """Lo que necesita un endpoint del portal: de qué taller y de qué cliente.

    Los dos salen de la sesión, que los recibió del enlace guardado (T10). Un
    endpoint del portal filtra siempre por `client_id`: RLS separa talleres, no
    clientes (arquitectura §4).
    """

    workshop_id: UUID
    client_id: UUID
    client: PortalClient
    session: AsyncSession


async def portal_context(user: Client) -> AsyncIterator[PortalContext]:
    """El taller de la sesión, fijado para RLS, y su cliente comprobado en cada
    petición (RNF-02)."""
    assert user.workshop_id is not None and user.client_id is not None
    async with workshop_transaction([user.workshop_id]) as session:
        try:
            client = await portal_auth_service.current_client(
                session,
                user.workshop_id,
                user.client_id,
                portal_epoch=user.portal_epoch,
                expires_at=user.portal_expires_at,
            )
        except PortalSessionEndedError:
            # Cerrada de verdad: el 401 hace que el navegador intente renovarla,
            # y sin esto lo conseguiría y volvería a llegar aquí, una y otra vez.
            assert user.session_handle is not None
            await end_session(user.session_handle)
            raise
        yield PortalContext(
            workshop_id=user.workshop_id,
            client_id=user.client_id,
            client=client,
            session=session,
        )


# scope="function": el commit antes de responder, como ActiveWorkshop.
Portal = Annotated[PortalContext, Depends(portal_context, scope="function")]
