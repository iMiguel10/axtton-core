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

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from supertokens_python.asyncio import delete_user, list_users_by_account_info
from supertokens_python.recipe.emailpassword.interfaces import (
    RecipeInterface as EmailPasswordRecipe,
)
from supertokens_python.recipe.emailpassword.interfaces import (
    SignInOkResult,
    WrongCredentialsError,
)
from supertokens_python.recipe.passwordless.asyncio import signinup
from supertokens_python.recipe.session.asyncio import (
    create_new_session as new_session,
)
from supertokens_python.recipe.session.asyncio import (
    get_all_session_handles_for_user,
    get_session_information,
    revoke_multiple_sessions,
    revoke_session,
)
from supertokens_python.recipe.session.interfaces import (
    RecipeInterface as SessionRecipe,
)
from supertokens_python.recipe.session.interfaces import SessionContainer
from supertokens_python.types import RecipeUserId
from supertokens_python.types.base import AccountInfoInput

from app.core.db import SessionFactory
from app.domain.actors import (
    ACTOR_CLAIM,
    CLIENT_CLAIM,
    PORTAL_EPOCH_CLAIM,
    PORTAL_EXPIRES_CLAIM,
    WORKSHOP_CLAIM,
    Actor,
)
from app.domain.portal import SESSION_LIFETIME, PortalLogin
from app.repositories import users as user_repo

logger = logging.getLogger(__name__)

# Lo que dice quién es una sesión: solo lo escribe este módulo.
IDENTITY_CLAIMS = (
    ACTOR_CLAIM,
    WORKSHOP_CLAIM,
    CLIENT_CLAIM,
    PORTAL_EPOCH_CLAIM,
    PORTAL_EXPIRES_CLAIM,
)

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
            if key not in IDENTITY_CLAIMS
        }
        login = user_context.get(PORTAL_LOGIN)
        if isinstance(login, PortalLogin):
            payload |= {
                ACTOR_CLAIM: Actor.CLIENT,
                WORKSHOP_CLAIM: str(login.workshop_id),
                CLIENT_CLAIM: str(login.client_id),
                PORTAL_EPOCH_CLAIM: login.portal_epoch,
                PORTAL_EXPIRES_CLAIM: int(
                    (datetime.now(UTC) + SESSION_LIFETIME).timestamp()
                ),
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


async def revoke_client_sessions(
    email: str, workshop_id: UUID, client_id: UUID
) -> None:
    """Cierra las sesiones de un cliente de un taller, y solo esas (T7, RF-47).

    Nunca `revoke_all_sessions_for_user`: el usuario passwordless es uno por email,
    y cerraría también sus sesiones en otros talleres. Solo se mira el de la receta
    passwordless: el mismo email puede ser además una cuenta de personal, que es
    otro usuario y no tiene nada que ver.

    **Si al usuario no le queda ninguna sesión, se borra**: es lo único que guarda
    su email en SuperTokens, y este email ya no debe estar ahí (RF-15, RNF-40). No
    hace falta saber si es cliente de otro taller, que sería cruzar talleres: nada
    nuestro guarda el id del usuario, y `signinup` lo vuelve a crear al entrar.

    Va después del commit y no es lo que corta el acceso (eso lo hace la cerradura
    al instante); evita que esas sesiones se sigan renovando. Si falla, queda en el
    registro: esas sesiones ya no sirven para nada.
    """
    try:
        users = await list_users_by_account_info(
            "public", AccountInfoInput(email=email)
        )
        for user in users:
            if not any(m.recipe_id == "passwordless" for m in user.login_methods):
                continue
            handles = await get_all_session_handles_for_user(user.id)
            closing: list[str] = []
            for handle in handles:
                info = await get_session_information(handle)
                claims = info.custom_claims_in_access_token_payload if info else {}
                if claims.get(WORKSHOP_CLAIM) == str(workshop_id) and claims.get(
                    CLIENT_CLAIM
                ) == str(client_id):
                    closing.append(handle)
            if closing:
                await revoke_multiple_sessions(closing)
            if len(closing) == len(handles):
                await delete_user(user.id)
    except Exception:
        logger.exception("No se pudieron cerrar las sesiones de un cliente")


async def end_session(session_handle: str) -> None:
    """Cierra una sesión del portal que ya no vale, para que no se siga renovando."""
    await revoke_session(session_handle)


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
