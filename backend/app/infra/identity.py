"""Cuentas de SuperTokens desde el backend (sin pasar por las rutas públicas).

Vive en infra/ porque habla con un sistema externo (el core de SuperTokens). Los
services no importan el SDK: llaman a estas funciones.
"""

from supertokens_python.recipe.emailpassword.asyncio import sign_in, sign_up
from supertokens_python.recipe.emailpassword.interfaces import (
    EmailAlreadyExistsError,
    SignInOkResult,
    SignUpOkResult,
)

from app.core.sessions import PASSWORD_CHECK_ONLY


class WrongPasswordError(Exception):
    """El email ya tiene cuenta y la contraseña no es la suya."""


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
