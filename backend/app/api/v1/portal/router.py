from fastapi import APIRouter, Depends

from app.api.v1.deps import require_client
from app.api.v1.portal import orders
from app.api.v1.portal.deps import Portal
from app.domain.actors import Actor
from app.schemas.portal import PortalMe

# Toda ruta de este router exige una sesión de cliente (A5). Las de entrar en el
# portal (su página, pedir y consumir el enlace) van aparte, en auth.py.
router = APIRouter(
    prefix="/api/v1/portal",
    tags=["portal"],
    dependencies=[Depends(require_client)],
)
# Los subrouters heredan la dependencia de actor del router padre.
router.include_router(orders.router)


@router.get("/me")
async def me(portal: Portal) -> PortalMe:
    return PortalMe(
        actor=Actor.CLIENT,
        workshop_id=portal.workshop_id,
        workshop_name=portal.client.workshop_name,
        timezone=portal.client.timezone,
        client_name=portal.client.client_name,
        language=portal.client.language,
    )
