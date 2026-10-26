"""Aceptar una invitación de superadministrador (RF-110). Pública, como la de
empleados: quien la usa todavía no tiene cuenta.

Usa app/platform/ porque la invitación es de la plataforma, no de un taller.
No es una excepción de R8 (que protege /workshop y /portal): es la misma vía que
/admin, solo que sin sesión, y la tabla que toca no la puede leer axtton_app.
"""

from fastapi import APIRouter, Depends, status

from app.api.rate_limit import limit_invitation_accept, limit_invitation_view
from app.platform import superadmins
from app.schemas.invitations import InvitationAccept, SuperadminInvitationRead

router = APIRouter(
    prefix="/api/v1/superadmin-invitations", tags=["superadmin-invitations"]
)


@router.get("/{token}", dependencies=[Depends(limit_invitation_view)])
async def view_invitation(token: str) -> SuperadminInvitationRead:
    return SuperadminInvitationRead(email=await superadmins.view(token))


@router.post(
    "/{token}/accept",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(limit_invitation_accept)],
)
async def accept_invitation(token: str, body: InvitationAccept) -> None:
    await superadmins.accept(token, body.password.get_secret_value())
