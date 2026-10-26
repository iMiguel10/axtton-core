from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Employee, Invitation, User


async def get(session: AsyncSession, employee_id: UUID) -> Employee | None:
    return await session.get(Employee, employee_id)


async def list_all(session: AsyncSession) -> list[tuple[Employee, bool]]:
    """Empleados del taller fijado y si tienen una invitación pendiente."""
    pending = (
        select(func.count())
        .where(
            Invitation.employee_id == Employee.id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > func.clock_timestamp(),
        )
        .scalar_subquery()
    )
    rows = await session.execute(select(Employee, pending > 0).order_by(Employee.name))
    return [(employee, has_pending) for employee, has_pending in rows]


async def count_with_access(session: AsyncSession, workshop_id: UUID) -> int:
    """Empleados activos con cuenta: lo que cuenta para el límite (§10)."""
    count = await session.scalar(
        select(func.count()).where(
            Employee.workshop_id == workshop_id,
            Employee.user_id.is_not(None),
            Employee.active,
        )
    )
    return count or 0


async def count_active_admins_with_access(
    session: AsyncSession, workshop_id: UUID
) -> int:
    """Para RF-05: un taller tiene siempre al menos un administrador que puede entrar."""
    count = await session.scalar(
        select(func.count()).where(
            Employee.workshop_id == workshop_id,
            Employee.role == "admin",
            Employee.active,
            Employee.user_id.is_not(None),
        )
    )
    return count or 0


async def get_active_for_user(
    session: AsyncSession, workshop_id: UUID, supertokens_user_id: str
) -> Employee | None:
    """El empleado activo con acceso de este usuario en el taller fijado.

    Es la comprobación del taller activo (A6, RNF-09): bajo RLS solo se ve el
    taller de la cabecera, así que si la persona no trabaja en él, no aparece.
    """
    query = (
        select(Employee)
        .join(User, User.id == Employee.user_id)
        .where(
            Employee.workshop_id == workshop_id,
            Employee.active,
            User.supertokens_user_id == supertokens_user_id,
        )
    )
    return (await session.scalars(query)).one_or_none()


async def revoke_pending_invitations(session: AsyncSession, employee_id: UUID) -> None:
    """Al reenviar una invitación, la anterior deja de servir."""
    await session.execute(
        update(Invitation)
        .where(
            Invitation.employee_id == employee_id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )


async def lock_staff(session: AsyncSession, workshop_id: UUID) -> None:
    """Pone en fila, hasta el final de la transacción, los cambios del personal
    de un taller que dependen de un recuento: que quede un administrador (RF-05)
    y que no se pase el límite de empleados con acceso (RF-114).

    Sin esto, dos transacciones a la vez cuentan cada una sin ver la otra (READ
    COMMITTED) y las dos pasan la comprobación: dos administradores que se quitan
    el rol mutuamente dejan el taller sin ninguno. Es un bloqueo consultivo de
    Postgres, por taller: no necesita permisos sobre ninguna tabla y se suelta
    solo al confirmar o deshacer.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"staff:{workshop_id}"},
    )


async def list_active(session: AsyncSession) -> list[Employee]:
    """Las fichas activas del taller fijado, por nombre."""
    rows = await session.scalars(
        select(Employee).where(Employee.active).order_by(Employee.name, Employee.id)
    )
    return list(rows)
