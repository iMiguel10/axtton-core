"""La cuenta de quien ha iniciado sesión (RF-122, RF-123).

Es un subrouter que se incluye en /workshop y en /admin: el personal y el
superadministrador comparten estas operaciones, y cada prefijo ya exige su
actor (A5). El cliente (portal) no tiene contraseña, así que no las tiene.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, SecretStr
from supertokens_python.recipe.session import SessionContainer
from supertokens_python.recipe.session.framework.fastapi import verify_session

from app.api.rate_limit import enforce
from app.core.errors import ForbiddenError, ValidationFailedError
from app.domain.rate_limits import PASSWORD_CHANGE_PER_USER
from app.infra import identity

router = APIRouter(prefix="/account", tags=["account"])

CurrentSession = Annotated[SessionContainer, Depends(verify_session())]


class PasswordChange(BaseModel):
    # SecretStr: en un error de validación sale como '**********', no en claro.
    current_password: SecretStr
    new_password: SecretStr = Field(min_length=10)


class SessionRead(BaseModel):
    created_at: datetime
    current: bool


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(body: PasswordChange, session: CurrentSession) -> None:
    """Exige la contraseña actual y cierra las DEMÁS sesiones (RF-122): si alguien
    tenía una abierta en otro dispositivo, deja de tenerla."""
    # Antes de comprobar la contraseña: si no, el límite no frenaría a quien la adivina.
    await enforce(PASSWORD_CHANGE_PER_USER, session.get_user_id())
    try:
        await identity.change_password(
            session.get_user_id(),
            body.current_password.get_secret_value(),
            body.new_password.get_secret_value(),
        )
    except identity.WrongPasswordError:
        raise ForbiddenError("wrong_password") from None
    except identity.WeakPasswordError:
        raise ValidationFailedError("weak_password") from None
    await identity.revoke_other_sessions(session.get_user_id(), session.get_handle())


@router.get("/sessions")
async def list_sessions(session: CurrentSession) -> list[SessionRead]:
    current = session.get_handle()
    return [
        SessionRead(created_at=info.created_at, current=info.handle == current)
        for info in await identity.list_sessions(session.get_user_id())
    ]


@router.post("/sessions/revoke-others", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_other_sessions(session: CurrentSession) -> None:
    """Cerrar todas las sesiones menos esta (RF-123)."""
    await identity.revoke_other_sessions(session.get_user_id(), session.get_handle())
