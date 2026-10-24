"""El ÚNICO sitio que escribe el actor en una sesión (arquitectura §2, invariante 4).

SuperTokens llama a `create_new_session` siempre que crea una sesión, venga del
inicio de sesión con contraseña o (en F4) del enlace mágico. Al sobrescribir esa
función aquí, el actor se decide en un solo punto y no hay forma de crear una
sesión sin él. Ningún otro código modifica el contenido de una sesión ya creada
(la prueba T11 lo vigila).
"""

from typing import Any

from supertokens_python.recipe.emailpassword.interfaces import (
    RecipeInterface as EmailPasswordRecipe,
)
from supertokens_python.recipe.emailpassword.interfaces import (
    SignInOkResult,
    WrongCredentialsError,
)
from supertokens_python.recipe.session.interfaces import (
    RecipeInterface as SessionRecipe,
)
from supertokens_python.recipe.session.interfaces import SessionContainer
from supertokens_python.types import RecipeUserId

from app.core.db import SessionFactory
from app.domain.actors import ACTOR_CLAIM, Actor
from app.repositories import users as user_repo

# Marca que el backend pone en user_context cuando solo quiere comprobar una
# contraseña (al aceptar una invitación), no iniciar sesión: en ese caso la
# cuenta propia puede no existir todavía, y es justo lo que se va a crear.
PASSWORD_CHECK_ONLY = "axtton_password_check_only"


class NoAccountError(Exception):
    """Un usuario de SuperTokens sin cuenta propia intentó obtener una sesión."""


async def actor_for(supertokens_user_id: str) -> Actor:
    """Decide el actor a partir de nuestra base de datos, nunca de la petición.

    F1: solo personal y superadministrador, por `users.kind`. El actor cliente
    llega en F4 con la receta passwordless.
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
        # Lo que viniera en el payload se sustituye: el actor solo lo decide actor_for.
        payload = {
            **(access_token_payload or {}),
            ACTOR_CLAIM: await actor_for(user_id),
        }
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
