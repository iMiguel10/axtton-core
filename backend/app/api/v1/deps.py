"""Las tres dependencias de actor (arquitectura A5, §2). Aquí, y en ningún otro
sitio, se decide qué actor puede entrar en cada prefijo de la API.

Cada router las declara una vez en `dependencies=[...]`, así que todas sus rutas
quedan protegidas por construcción: una ruta nueva no puede olvidarlo.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from supertokens_python.recipe.session import SessionContainer
from supertokens_python.recipe.session.framework.fastapi import verify_session

from app.core.errors import ForbiddenError
from app.domain.actors import (
    ACTOR_CLAIM,
    CLIENT_CLAIM,
    PORTAL_EPOCH_CLAIM,
    PORTAL_EXPIRES_CLAIM,
    WORKSHOP_CLAIM,
    Actor,
)


@dataclass(frozen=True)
class CurrentUser:
    supertokens_user_id: str
    actor: Actor
    # Solo en una sesión de cliente: el taller y el cliente del enlace con el que
    # entró (core/sessions.py). El personal elige taller en cada petición (A6).
    workshop_id: UUID | None = None
    client_id: UUID | None = None
    # La cerradura y la caducidad con las que se creó, y la sesión, para cerrarla
    # si ya no vale. Se comprueban en la dependencia del portal.
    portal_epoch: int | None = None
    portal_expires_at: int | None = None
    session_handle: str | None = None


def _require(actor: Actor) -> Callable[..., Awaitable[CurrentUser]]:
    async def dependency(
        # verify_session responde 401 sin una sesión válida: sin token, con uno
        # caducado o con uno cuya firma no coincide (T9).
        session: Annotated[SessionContainer, Depends(verify_session())],
    ) -> CurrentUser:
        # El actor se lee SIEMPRE de la sesión verificada, nunca de una cabecera
        # ni del cuerpo de la petición (invariante 4).
        payload = session.get_access_token_payload()
        if payload.get(ACTOR_CLAIM) != actor:
            raise ForbiddenError("wrong_actor")
        user = CurrentUser(supertokens_user_id=session.get_user_id(), actor=actor)
        if actor is Actor.CLIENT:
            # Los puso el servidor al crear la sesión, y van firmados (T9).
            user = CurrentUser(
                supertokens_user_id=user.supertokens_user_id,
                actor=actor,
                workshop_id=UUID(payload[WORKSHOP_CLAIM]),
                client_id=UUID(payload[CLIENT_CLAIM]),
                portal_epoch=payload.get(PORTAL_EPOCH_CLAIM),
                portal_expires_at=payload.get(PORTAL_EXPIRES_CLAIM),
                session_handle=session.get_handle(),
            )
        return user

    dependency.__name__ = f"require_{actor.value}"
    return dependency


require_staff = _require(Actor.STAFF)
require_superadmin = _require(Actor.SUPERADMIN)
require_client = _require(Actor.CLIENT)

Staff = Annotated[CurrentUser, Depends(require_staff)]
Superadmin = Annotated[CurrentUser, Depends(require_superadmin)]
Client = Annotated[CurrentUser, Depends(require_client)]
