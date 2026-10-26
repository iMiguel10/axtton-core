"""El directorio del personal del taller activo: lo ve todo el personal."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.v1.workshop.deps import WorkshopContext, require
from app.domain.permissions import Action
from app.schemas.employees import StaffRead
from app.services import employees as employee_service

router = APIRouter(prefix="/staff")

Viewer = Annotated[WorkshopContext, Depends(require(Action.VIEW_ORDERS))]


@router.get("")
async def list_staff(workshop: Viewer) -> list[StaffRead]:
    """Fichas activas (id y nombre), para anotar quién hizo un trabajo (RF-23)."""
    staff = await employee_service.list_staff(workshop.session)
    return [StaffRead(id=member.id, name=member.name) for member in staff]
