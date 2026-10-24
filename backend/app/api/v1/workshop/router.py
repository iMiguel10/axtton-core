from fastapi import APIRouter, Depends

from app.api.v1.deps import Staff, require_staff
from app.schemas.session import WhoAmI

# Toda ruta de este router exige una sesión de personal (arquitectura A5).
router = APIRouter(
    prefix="/api/v1/workshop",
    tags=["workshop"],
    dependencies=[Depends(require_staff)],
)


@router.get("/me")
async def me(user: Staff) -> WhoAmI:
    """Quién soy. En el paso 4 añadirá los talleres en los que trabajo."""
    return WhoAmI(actor=user.actor)
