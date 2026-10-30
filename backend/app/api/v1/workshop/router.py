from fastapi import APIRouter, Depends

from app.api.v1 import account
from app.api.v1.deps import Staff, require_staff
from app.api.v1.workshop import (
    audit,
    clients,
    employees,
    limits,
    quotes,
    search,
    settings,
    staff,
    vehicles,
    work_orders,
    worklog,
)
from app.api.v1.workshop.deps import ActiveWorkshop

# Excepción con nombre de la regla R8 (arquitectura §4): saber en qué talleres
# trabaja la persona exige cruzar talleres. Solo devuelve los suyos.
from app.platform.memberships import list_for_user
from app.schemas.session import ActiveWorkshopRead, StaffMe, WorkshopMembership

# Toda ruta de este router exige una sesión de personal (arquitectura A5).
router = APIRouter(
    prefix="/api/v1/workshop",
    tags=["workshop"],
    dependencies=[Depends(require_staff)],
)
# Los subrouters heredan la dependencia de actor del router padre.
router.include_router(employees.router)
router.include_router(staff.router)
router.include_router(limits.router)
router.include_router(settings.router)
router.include_router(clients.router)
router.include_router(search.router)
router.include_router(vehicles.router)
router.include_router(work_orders.router)
router.include_router(worklog.router)
router.include_router(quotes.router)
router.include_router(audit.router)
router.include_router(account.router)


@router.get("/me")
async def me(user: Staff) -> StaffMe:
    """Quién soy y en qué talleres puedo trabajar (para el selector, RF-08).

    No exige X-Workshop-Id: es lo que se pide antes de elegir taller.
    """
    memberships = await list_for_user(user.supertokens_user_id)
    return StaffMe(
        actor=user.actor,
        workshops=[WorkshopMembership(**m.__dict__) for m in memberships],
    )


@router.get("/active")
async def active_workshop(workshop: ActiveWorkshop) -> ActiveWorkshopRead:
    """El taller de la cabecera X-Workshop-Id, validado, y mi rol en él."""
    return ActiveWorkshopRead(
        workshop_id=workshop.workshop_id,
        employee_id=workshop.employee_id,
        role=workshop.role,
    )
