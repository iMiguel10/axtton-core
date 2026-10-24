from fastapi import APIRouter, Depends

from app.api.v1.deps import Superadmin, require_superadmin
from app.schemas.session import WhoAmI

# Toda ruta de este router exige una sesión de superadministrador (A5). Sus
# endpoints solo llaman a app/platform/ y nunca devuelven datos de un taller.
router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_superadmin)],
)


@router.get("/me")
async def me(user: Superadmin) -> WhoAmI:
    return WhoAmI(actor=user.actor)
