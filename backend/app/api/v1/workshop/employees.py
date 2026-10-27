"""Empleados del taller activo (RF-03 a RF-06). Solo para quien puede gestionarlos."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, status

from app.api.deps import get_email_sender
from app.api.v1.workshop.deps import WorkshopContext, require
from app.core.config import get_settings
from app.domain.emails import invitation_email
from app.domain.invitations import invitation_path
from app.domain.permissions import Action, can
from app.infra.email import EmailSender, compose
from app.schemas.employees import (
    EmployeeCreate,
    EmployeeCreated,
    EmployeeRead,
    EmployeeUpdate,
    InvitationCreate,
    InvitationQueued,
    VersionOnly,
)
from app.services import employees as employee_service

router = APIRouter(prefix="/employees")

Manager = Annotated[WorkshopContext, Depends(require(Action.MANAGE_EMPLOYEES))]


@router.get("")
async def list_employees(workshop: Manager) -> list[EmployeeRead]:
    views = await employee_service.list_employees(
        workshop.session, show_costs=can(workshop.role, Action.VIEW_COSTS)
    )
    return [EmployeeRead(**view.__dict__) for view in views]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_employee(body: EmployeeCreate, workshop: Manager) -> EmployeeCreated:
    employee_id = await employee_service.create_employee(
        workshop.session,
        workshop.workshop_id,
        workshop.user_id,
        name=body.name,
        position=body.position,
        role=body.role.value,
        hourly_cost_cents=body.hourly_cost_cents,
    )
    return EmployeeCreated(id=employee_id)


@router.patch("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_employee(
    employee_id: UUID, body: EmployeeUpdate, workshop: Manager
) -> None:
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    if "role" in changes and changes["role"] is not None:
        changes["role"] = changes["role"].value
    await employee_service.update_employee(
        workshop.session,
        workshop.workshop_id,
        workshop.user_id,
        employee_id,
        expected_version=body.version,
        changes=changes,
    )


@router.post("/{employee_id}/access/remove", status_code=status.HTTP_204_NO_CONTENT)
async def remove_access(
    employee_id: UUID, body: VersionOnly, workshop: Manager
) -> None:
    await employee_service.remove_access(
        workshop.session,
        workshop.workshop_id,
        workshop.user_id,
        employee_id,
        expected_version=body.version,
    )


@router.post("/{employee_id}/invitation")
async def invite(
    employee_id: UUID,
    body: InvitationCreate,
    workshop: Manager,
    background: BackgroundTasks,
    email_sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> InvitationQueued:
    """Invitar o reinvitar a una ficha sin acceso.

    El email va en una tarea en segundo plano de FastAPI, que se ejecuta DESPUÉS
    de enviar la respuesta, y por tanto después del commit de la transacción
    del taller: nunca sale un email para una invitación que no llegó a guardarse.
    Si el envío falla, la invitación existe y se puede reenviar (en F5, la bandeja
    de avisos reintentará sola).
    """
    invitation = await employee_service.invite(
        workshop.session,
        workshop.workshop_id,
        workshop.user_id,
        employee_id,
        email=str(body.email),
    )
    if not email_sender.enabled:
        return InvitationQueued(invitation_email_queued=False)
    content = invitation_email(
        employee_name=invitation.employee_name,
        workshop_name=invitation.workshop_name,
        link=get_settings().app_url
        + invitation_path(workshop.workshop_id, invitation.token),
        first_admin=False,
    )
    background.add_task(email_sender.send, compose(invitation.email, content))
    return InvitationQueued(invitation_email_queued=True)
