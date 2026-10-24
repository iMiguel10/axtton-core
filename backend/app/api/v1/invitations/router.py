"""Aceptar una invitación: la única ruta de /api/v1 que no exige sesión.

Quien la usa todavía no tiene cuenta. No pertenece a ninguno de los tres
prefijos de actor (A5); por eso T1 y T2 no la cubren y tiene sus propias pruebas.
"""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import workshop_transaction
from app.core.errors import ConflictError
from app.schemas.invitations import InvitationAccept, InvitationRead
from app.services import invitations as invitation_service

router = APIRouter(prefix="/api/v1/invitations", tags=["invitations"])


async def invitation_session(workshop_id: UUID) -> AsyncIterator[AsyncSession]:
    """Transacción con el taller del enlace fijado para RLS."""
    try:
        async with workshop_transaction([workshop_id]) as session:
            yield session
    except IntegrityError as error:
        # UNIQUE (workshop_id, user_id): esa persona ya trabaja en este taller.
        raise ConflictError("already_an_employee") from error


InvitationSession = Annotated[AsyncSession, Depends(invitation_session)]


@router.get("/{workshop_id}/{token}")
async def view_invitation(token: str, session: InvitationSession) -> InvitationRead:
    view = await invitation_service.view(session, token)
    return InvitationRead(**view.__dict__)


@router.post("/{workshop_id}/{token}/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept_invitation(
    workshop_id: UUID, token: str, body: InvitationAccept, session: InvitationSession
) -> None:
    await invitation_service.accept(
        session, workshop_id, token, body.password.get_secret_value()
    )
