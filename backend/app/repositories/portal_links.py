"""Enlaces mágicos del portal, siempre bajo RLS con el taller fijado."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PortalLink


async def add(
    session: AsyncSession,
    workshop_id: UUID,
    client_id: UUID,
    token_hash: bytes,
    expires_at: datetime,
) -> None:
    session.add(
        PortalLink(
            workshop_id=workshop_id,
            client_id=client_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )
    await session.flush()


async def use_if_open(session: AsyncSession, token_hash: bytes) -> UUID | None:
    """Marca el enlace como usado si aún vale, y devuelve su cliente.

    Una sola sentencia que comprueba y cierra a la vez: si dos peticiones usan
    el mismo enlace, la segunda espera al bloqueo de la fila, vuelve a evaluar
    la condición con el enlace ya usado y no cambia nada (T6). La hora es la de
    la base de datos, como en el resto de caducidades.
    """
    now = func.clock_timestamp()
    statement = (
        update(PortalLink)
        .where(
            PortalLink.token_hash == token_hash,
            PortalLink.used_at.is_(None),
            PortalLink.revoked_at.is_(None),
            PortalLink.expires_at > now,
        )
        .values(used_at=now)
        .returning(PortalLink.client_id)
    )
    return (await session.scalars(statement)).one_or_none()


async def revoke_open_for_client(session: AsyncSession, client_id: UUID) -> None:
    """Revoca los enlaces pendientes de un cliente (cambio de email, anonimizar).

    Los ya cerrados no se tocan: el trigger portal_links_closed_frozen lo
    impediría, y no hace falta.
    """
    await session.execute(
        update(PortalLink)
        .where(
            PortalLink.client_id == client_id,
            PortalLink.used_at.is_(None),
            PortalLink.revoked_at.is_(None),
        )
        .values(revoked_at=func.clock_timestamp())
    )
