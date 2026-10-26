"""Gestión de empleados desde el taller (RF-03 a RF-06).

Todo se ejecuta en la transacción del taller activo (RLS fijada). Los errores
deshacen la transacción entera: si una comprobación falla al final, nada de lo
anterior queda guardado.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.core.tokens import hash_token, new_token
from app.domain.invitations import INVITATION_VALIDITY
from app.models import AuditEntry, Employee, Invitation, Workshop
from app.repositories import employees as employee_repo

# Campos que se pueden cambiar con PATCH (la cuenta ligada, no: eso es dar o
# quitar acceso, que tienen sus propias operaciones).
EDITABLE = ("name", "position", "role", "active", "hourly_cost_cents")


@dataclass(frozen=True)
class EmployeeView:
    id: UUID
    name: str
    position: str | None
    role: str
    active: bool
    has_access: bool
    invitation_pending: bool
    hourly_cost_cents: int | None
    version: int


def _audit(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    action: str,
    employee_id: UUID,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEntry(
            workshop_id=workshop_id,
            actor_user_id=user_id,
            action=action,
            target_type="employee",
            target_id=employee_id,
            details=details or {},
        )
    )


async def _ensure_an_admin_remains(session: AsyncSession, workshop_id: UUID) -> None:
    """RF-05, comprobado sobre el resultado: se aplica el cambio, se cuenta y, si
    no queda ningún administrador activo con acceso, se deshace todo."""
    await session.flush()
    if await employee_repo.count_active_admins_with_access(session, workshop_id) == 0:
        raise ConflictError("last_admin")


async def _get(session: AsyncSession, employee_id: UUID) -> Employee:
    employee = await employee_repo.get(session, employee_id)
    if employee is None:
        raise NotFoundError("employee_not_found")
    return employee


def _check_version(employee: Employee, expected: int) -> None:
    """Bloqueo optimista a nivel HTTP (RNF-15): el cliente manda la versión que
    leyó. Si otra persona guardó entretanto, la versión ya es otra y no se pisa
    su cambio. (SQLAlchemy además vigila la versión dentro de la transacción.)"""
    if employee.version != expected:
        raise ConflictError("modified_by_someone_else")


async def list_employees(
    session: AsyncSession, *, show_costs: bool
) -> list[EmployeeView]:
    return [
        EmployeeView(
            id=employee.id,
            name=employee.name,
            position=employee.position,
            role=employee.role,
            active=employee.active,
            has_access=employee.user_id is not None,
            invitation_pending=pending,
            hourly_cost_cents=employee.hourly_cost_cents if show_costs else None,
            version=employee.version,
        )
        for employee, pending in await employee_repo.list_all(session)
    ]


async def create_employee(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    *,
    name: str,
    position: str | None,
    role: str,
    hourly_cost_cents: int | None,
) -> UUID:
    """Una ficha sin acceso (RF-03): existe aunque nunca entre en la aplicación."""
    employee = Employee(
        workshop_id=workshop_id,
        name=name,
        position=position,
        role=role,
        hourly_cost_cents=hourly_cost_cents,
    )
    session.add(employee)
    await session.flush()
    _audit(
        session, workshop_id, user_id, "employee_created", employee.id, {"role": role}
    )
    return employee.id


async def update_employee(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    employee_id: UUID,
    *,
    expected_version: int,
    changes: dict[str, Any],
) -> None:
    # Antes de leer: así la ficha y el recuento de administradores se leen ya
    # con los cambios de quien iba delante.
    await employee_repo.lock_staff(session, workshop_id)
    employee = await _get(session, employee_id)
    _check_version(employee, expected_version)
    audited: dict[str, list[Any]] = {}
    for field in EDITABLE:
        if field in changes and changes[field] != getattr(employee, field):
            audited[field] = [getattr(employee, field), changes[field]]
            setattr(employee, field, changes[field])
    if not audited:
        return
    await _ensure_an_admin_remains(session, workshop_id)
    _audit(session, workshop_id, user_id, "employee_updated", employee_id, audited)


async def remove_access(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    employee_id: UUID,
    *,
    expected_version: int,
) -> None:
    """Quitar el acceso (RF-06): la ficha se queda (su nombre sigue en lo que
    hizo) y la cuenta deja de estar ligada. Surte efecto en la siguiente petición
    de esa persona, porque el taller activo se valida en cada una."""
    await employee_repo.lock_staff(session, workshop_id)
    employee = await _get(session, employee_id)
    _check_version(employee, expected_version)
    if employee.user_id is None:
        return
    employee.user_id = None
    await employee_repo.revoke_pending_invitations(session, employee_id)
    await _ensure_an_admin_remains(session, workshop_id)
    _audit(session, workshop_id, user_id, "access_removed", employee_id)


@dataclass(frozen=True)
class NewInvitation:
    token: str
    email: str
    employee_name: str
    workshop_name: str


async def invite(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    employee_id: UUID,
    *,
    email: str,
) -> NewInvitation:
    """Invitar (o reinvitar) a una ficha sin acceso (RF-04). La invitación
    anterior, si la hubiera, deja de servir."""
    # En fila: dos reinvitaciones a la vez dejarían dos enlaces válidos.
    await employee_repo.lock_staff(session, workshop_id)
    employee = await _get(session, employee_id)
    if employee.user_id is not None:
        raise ConflictError("employee_already_has_access")
    workshop = await session.get(Workshop, workshop_id)
    assert workshop is not None
    await employee_repo.revoke_pending_invitations(session, employee_id)
    token = new_token()
    session.add(
        Invitation(
            workshop_id=workshop_id,
            employee_id=employee_id,
            email=email,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + INVITATION_VALIDITY,
            created_by_user_id=user_id,
        )
    )
    # Sin el email en la auditoría: no guarda datos personales que no necesita.
    _audit(session, workshop_id, user_id, "invitation_sent", employee_id)
    return NewInvitation(token, email, employee.name, workshop.name)
