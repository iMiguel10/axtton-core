from fastapi import APIRouter, Depends

from app.api.v1.deps import Client, require_client
from app.schemas.session import WhoAmI

# Toda ruta de este router exige una sesión de cliente (A5). Hasta F4 no existe
# forma de obtenerla: el router está para que las pruebas T1 y T2 cubran el prefijo
# desde ahora.
router = APIRouter(
    prefix="/api/v1/portal",
    tags=["portal"],
    dependencies=[Depends(require_client)],
)


@router.get("/me")
async def me(user: Client) -> WhoAmI:
    return WhoAmI(actor=user.actor)
