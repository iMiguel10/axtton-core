"""Las tres dependencias de actor (arquitectura A5, §2). Aquí, y en ningún otro
sitio, se decide qué actor puede entrar en cada prefijo de la API.

Cada router las declara una vez en `dependencies=[...]`, así que todas sus rutas
quedan protegidas por construcción: una ruta nueva no puede olvidarlo.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from supertokens_python.recipe.session import SessionContainer
from supertokens_python.recipe.session.framework.fastapi import verify_session

from app.core.errors import ForbiddenError
from app.domain.actors import ACTOR_CLAIM, Actor


@dataclass(frozen=True)
class CurrentUser:
    supertokens_user_id: str
    actor: Actor


def _require(actor: Actor) -> Callable[..., Awaitable[CurrentUser]]:
    async def dependency(
        # verify_session responde 401 sin una sesión válida: sin token, con uno
        # caducado o con uno cuya firma no coincide (T9).
        session: Annotated[SessionContainer, Depends(verify_session())],
    ) -> CurrentUser:
        # El actor se lee SIEMPRE de la sesión verificada, nunca de una cabecera
        # ni del cuerpo de la petición (invariante 4).
        if session.get_access_token_payload().get(ACTOR_CLAIM) != actor:
            raise ForbiddenError("wrong_actor")
        return CurrentUser(supertokens_user_id=session.get_user_id(), actor=actor)

    dependency.__name__ = f"require_{actor.value}"
    return dependency


require_staff = _require(Actor.STAFF)
require_superadmin = _require(Actor.SUPERADMIN)
require_client = _require(Actor.CLIENT)

Staff = Annotated[CurrentUser, Depends(require_staff)]
Superadmin = Annotated[CurrentUser, Depends(require_superadmin)]
Client = Annotated[CurrentUser, Depends(require_client)]
