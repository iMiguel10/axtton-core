from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import Staff
from app.core.db import workshop_transaction
from app.core.errors import ForbiddenError, NotFoundError
from app.domain.permissions import Action, can
from app.models import Workshop
from app.repositories import employees as employee_repo


@dataclass(frozen=True)
class WorkshopContext:
    """Lo que necesita un endpoint del taller: dónde, quién y con qué rol."""

    workshop_id: UUID
    employee_id: UUID
    user_id: UUID
    role: str
    session: AsyncSession


async def workshop_context(
    user: Staff,
    x_workshop_id: Annotated[UUID, Header()],
) -> AsyncIterator[WorkshopContext]:
    """Taller activo validado (arquitectura A6, RNF-09, T3 y T8).

    La cabecera X-Workshop-Id dice en qué taller se quiere trabajar; aquí se
    comprueba, EN CADA PETICIÓN, que la persona es un empleado activo de ese
    taller y que el taller está activo. Si no, 404: no se revela si el taller
    existe.

    Por hacerse en cada petición, desactivar a un empleado o un taller corta el
    acceso al instante, también con la sesión abierta (RF-06, RF-113), sin cerrar
    sus sesiones: la persona puede seguir trabajando en sus otros talleres.
    """
    async with workshop_transaction([x_workshop_id]) as session:
        workshop = await session.get(Workshop, x_workshop_id)
        employee = await employee_repo.get_active_for_user(
            session, x_workshop_id, user.supertokens_user_id
        )
        if workshop is None or workshop.status != "active" or employee is None:
            raise NotFoundError("workshop_not_found")
        assert employee.user_id is not None
        yield WorkshopContext(
            workshop_id=x_workshop_id,
            employee_id=employee.id,
            user_id=employee.user_id,
            role=employee.role,
            session=session,
        )


# scope="function": la salida del `yield` (el commit de workshop_transaction) se
# ejecuta al terminar el endpoint, ANTES de enviar la respuesta y antes de las
# BackgroundTasks. Con el valor por defecto ("request") el commit llegaba después
# de ambas: un 2xx podía no estar guardado y un email de invitación salir antes
# que su invitación (hallazgo del cierre de F1, tests/test_commit_order.py).
ActiveWorkshop = Annotated[WorkshopContext, Depends(workshop_context, scope="function")]


def require(action: Action) -> Callable[..., Awaitable[WorkshopContext]]:
    """Exige que el rol de la persona EN ESTE TALLER permita la acción (RNF-03).

    Quien es admin en un taller y mecánico en otro tiene, en cada uno, los
    permisos de su rol allí: el rol sale del taller activo, no de la sesión.
    """

    async def dependency(workshop: ActiveWorkshop) -> WorkshopContext:
        if not can(workshop.role, action):
            raise ForbiddenError("not_allowed")
        return workshop

    dependency.__name__ = f"require_{action.value}"
    return dependency
