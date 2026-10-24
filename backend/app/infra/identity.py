"""Cuentas de SuperTokens desde el backend (sin pasar por las rutas públicas).

Vive en infra/ porque habla con un sistema externo (el core de SuperTokens). Los
services no importan el SDK: llaman a estas funciones.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from supertokens_python.asyncio import get_user
from supertokens_python.recipe.emailpassword.asyncio import (
    sign_in,
    sign_up,
    update_email_or_password,
)
from supertokens_python.recipe.emailpassword.interfaces import (
    EmailAlreadyExistsError,
    PasswordPolicyViolationError,
    SignInOkResult,
    SignUpOkResult,
)
from supertokens_python.recipe.session.asyncio import (
    get_all_session_handles_for_user,
    get_session_information,
    revoke_multiple_sessions,
)
from supertokens_python.types import RecipeUserId

from app.core.sessions import PASSWORD_CHECK_ONLY


class WrongPasswordError(Exception):
    """El email ya tiene cuenta y la contraseña no es la suya."""


class WeakPasswordError(Exception):
    """La contraseña nueva no cumple la política de SuperTokens."""


async def email_of(supertokens_user_id: str) -> str:
    user = await get_user(supertokens_user_id)
    assert user is not None and user.emails
    return user.emails[0]


async def change_password(supertokens_user_id: str, current: str, new: str) -> None:
    """Cambiar la contraseña exige la actual (RF-122): con una sesión robada no
    basta para quedarse con la cuenta."""
    checked = await sign_in(
        "public",
        await email_of(supertokens_user_id),
        current,
        user_context={PASSWORD_CHECK_ONLY: True},
    )
    if not isinstance(checked, SignInOkResult):
        raise WrongPasswordError(supertokens_user_id)
    result = await update_email_or_password(
        RecipeUserId(supertokens_user_id), password=new, apply_password_policy=True
    )
    if isinstance(result, PasswordPolicyViolationError):
        raise WeakPasswordError(result.failure_reason)


@dataclass(frozen=True)
class SessionInfo:
    handle: str
    created_at: datetime


async def list_sessions(supertokens_user_id: str) -> list[SessionInfo]:
    sessions = []
    for handle in await get_all_session_handles_for_user(supertokens_user_id):
        info = await get_session_information(handle)
        if info is not None:
            created = datetime.fromtimestamp(info.time_created / 1000, tz=UTC)
            sessions.append(SessionInfo(handle, created))
    return sorted(sessions, key=lambda s: s.created_at)


async def revoke_other_sessions(supertokens_user_id: str, keep: str) -> None:
    """Cierra todas las sesiones de la cuenta menos la que hace la petición."""
    handles = await get_all_session_handles_for_user(supertokens_user_id)
    await revoke_multiple_sessions([h for h in handles if h != keep])


async def create_or_verify_account(email: str, password: str) -> str:
    """Devuelve el id de SuperTokens de la cuenta de ese email.

    - Si no existe, la crea con esa contraseña.
    - Si ya existe, exige SU contraseña: así quien acepta una invitación
      demuestra que la cuenta es suya antes de añadirle un taller (RF-07).
      Es también lo que permite reintentar si una aceptación anterior falló a
      medias y dejó la cuenta de SuperTokens creada sin su fila en `users`.
    """
    created = await sign_up("public", email, password)
    if isinstance(created, SignUpOkResult):
        return created.user.id
    if not isinstance(created, EmailAlreadyExistsError):  # pragma: no cover
        # Solo ocurre con la vinculación de cuentas, que no se usa (§2).
        raise TypeError(f"sign_up: {created.__class__.__name__}")

    checked = await sign_in(
        "public", email, password, user_context={PASSWORD_CHECK_ONLY: True}
    )
    if not isinstance(checked, SignInOkResult):
        raise WrongPasswordError(email)
    return checked.user.id
