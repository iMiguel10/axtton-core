"""El ÚNICO sitio que escribe el actor en una sesión (arquitectura §2, invariante 4).

SuperTokens llama a `create_new_session` siempre que crea una sesión, venga del
inicio de sesión con contraseña o del enlace mágico del portal. Al sobrescribir
esa función aquí, el actor se decide en un solo punto y no hay forma de crear una
sesión sin él. Ningún otro código modifica el contenido de una sesión ya creada
(la prueba T11 lo vigila).

La sesión de un cliente (F4) solo nace de `create_client_session`, con el
`PortalLogin` que devuelve consumir un enlace: el taller y el cliente salen del
enlace guardado, nunca de la petición (T10).
"""

from typing import Any

from fastapi import Request
from supertokens_python.recipe.emailpassword.interfaces import (
    RecipeInterface as EmailPasswordRecipe,
)
from supertokens_python.recipe.emailpassword.interfaces import (
    SignInOkResult,
    WrongCredentialsError,
)
from supertokens_python.recipe.passwordless.asyncio import signinup
from supertokens_python.recipe.session.asyncio import create_new_session as new_session
from supertokens_python.recipe.session.interfaces import (
    RecipeInterface as SessionRecipe,
)
from supertokens_python.recipe.session.interfaces import SessionContainer
from supertokens_python.types import RecipeUserId

from app.core.db import SessionFactory
from app.domain.actors import ACTOR_CLAIM, CLIENT_CLAIM, WORKSHOP_CLAIM, Actor
from app.domain.portal import PortalLogin
from app.repositories import users as user_repo

# Marca que el backend pone en user_context cuando solo quiere comprobar una
# contraseña (al aceptar una invitación), no iniciar sesión: en ese caso la
# cuenta propia puede no existir todavía, y es justo lo que se va a crear.
PASSWORD_CHECK_ONLY = "axtton_password_check_only"

# Dónde lleva `create_client_session` el PortalLogin hasta `create_new_session`.
# El user_context lo construye el backend: una petición no puede escribir en él.
PORTAL_LOGIN = "axtton_portal_login"


class NoAccountError(Exception):
    """Un usuario de SuperTokens sin cuenta propia intentó obtener una sesión."""


async def actor_for(supertokens_user_id: str) -> Actor:
    """El actor del personal y del superadministrador, de `users.kind`.

    Decidido a partir de nuestra base de datos, nunca de la petición. Un cliente
    no tiene fila en `users`: su sesión solo sale de `create_client_session`.
    """
    async with SessionFactory() as session:
        user = await user_repo.get_by_supertokens_id(session, supertokens_user_id)
    if user is None:
        raise NoAccountError(supertokens_user_id)
    return Actor(user.kind)


def session_override(original: SessionRecipe) -> SessionRecipe:
    original_create = original.create_new_session

    async def create_new_session(
        user_id: str,
        recipe_user_id: RecipeUserId,
        access_token_payload: dict[str, Any] | None,
        session_data_in_database: dict[str, Any] | None,
        disable_anti_csrf: bool | None,
        tenant_id: str,
        user_context: dict[str, Any],
    ) -> SessionContainer:
        # Lo que viniera en el payload sobre quién es se descarta: el actor, el
        # taller y el cliente solo los decide este módulo.
        payload = {
            key: value
            for key, value in (access_token_payload or {}).items()
            if key not in (ACTOR_CLAIM, WORKSHOP_CLAIM, CLIENT_CLAIM)
        }
        login = user_context.get(PORTAL_LOGIN)
        if isinstance(login, PortalLogin):
            payload |= {
                ACTOR_CLAIM: Actor.CLIENT,
                WORKSHOP_CLAIM: str(login.workshop_id),
                CLIENT_CLAIM: str(login.client_id),
            }
        else:
            payload[ACTOR_CLAIM] = await actor_for(user_id)
        return await original_create(
            user_id,
            recipe_user_id,
            payload,
            session_data_in_database,
            disable_anti_csrf,
            tenant_id,
            user_context,
        )

    original.create_new_session = create_new_session  # type: ignore[method-assign]
    return original


async def create_client_session(request: Request, login: PortalLogin) -> None:
    """Abre la sesión del portal para el cliente de un enlace ya consumido.

    El usuario de SuperTokens es el de la receta passwordless para ese email, uno
    solo aunque sea cliente de varios talleres: `signinup` lo crea la primera vez
    y lo devuelve las siguientes, sin enviar ningún código. Lo que separa los
    talleres es la sesión, que lleva el taller y el cliente del enlace (RF-45).
    Es otro usuario que el del personal con el mismo email (sin vinculación de
    cuentas, arquitectura §2): Ana, mecánica en un taller y clienta de otro,
    recibe aquí siempre una sesión de cliente (T10).

    Las cookies (o, en modo cabecera, los tokens) los pone en la respuesta el
    middleware de SuperTokens.
    """
    result = await signinup("public", email=login.email, phone_number=None)
    await new_session(
        request,
        "public",
        result.user.login_methods[0].recipe_user_id,
        user_context={PORTAL_LOGIN: login},
    )


def emailpassword_override(original: EmailPasswordRecipe) -> EmailPasswordRecipe:
    """Una cuenta de SuperTokens sin cuenta propia no inicia sesión.

    Puede quedar una si falla algo entre crear el usuario en SuperTokens y crear
    su fila en `users` (al aceptar una invitación, paso 4). Responde como una
    contraseña incorrecta: no revela que la cuenta existe.
    """
    original_sign_in = original.sign_in

    async def sign_in(
        email: str,
        password: str,
        tenant_id: str,
        session: SessionContainer | None,
        should_try_linking_with_session_user: bool | None,
        user_context: dict[str, Any],
    ) -> Any:
        result = await original_sign_in(
            email,
            password,
            tenant_id,
            session,
            should_try_linking_with_session_user,
            user_context,
        )
        if isinstance(result, SignInOkResult) and not user_context.get(
            PASSWORD_CHECK_ONLY
        ):
            try:
                await actor_for(result.user.id)
            except NoAccountError:
                return WrongCredentialsError()
        return result

    original.sign_in = sign_in  # type: ignore[method-assign]
    return original
