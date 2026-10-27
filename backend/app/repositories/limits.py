"""Cuánto lleva gastado un taller de cada límite (especificación §10).

Bajo RLS, como todo lo del taller: cuenta solo sus filas. La plataforma cuenta
lo de todos los talleres por su lado (platform/workshops.py), sin pasar por aquí.
"""

from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.limits import Resource, limit_column
from app.models import Client, Employee, Vehicle, WorkOrder, Workshop


async def lock(session: AsyncSession, workshop_id: UUID, resource: Resource) -> None:
    """Pone en fila, hasta el final de la transacción, las altas de un recurso en
    un taller. Sin esto, dos altas a la vez cuentan cada una sin ver la otra (READ
    COMMITTED) y las dos caben en el último hueco. Bloqueo consultivo, como
    employee_repo.lock_staff: no toca ninguna fila."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"limit:{resource.value}:{workshop_id}"},
    )


async def limit_of(session: AsyncSession, workshop_id: UUID, resource: Resource) -> int:
    value = await session.scalar(
        select(getattr(Workshop, limit_column(resource))).where(
            Workshop.id == workshop_id
        )
    )
    assert value is not None
    return int(value)


async def usage(session: AsyncSession, workshop_id: UUID, resource: Resource) -> int:
    """Cuántos hay ya. Las órdenes, las abiertas este mes en la zona del taller
    (el mes empieza a medianoche de Madrid, no de UTC)."""
    match resource:
        case Resource.EMPLOYEES_WITH_ACCESS:
            query = select(func.count()).where(
                Employee.user_id.is_not(None), Employee.active
            )
        case Resource.EMPLOYEES:
            query = select(func.count()).where(Employee.active)
        case Resource.CLIENTS:
            query = select(func.count()).select_from(Client)
        case Resource.VEHICLES:
            query = select(func.count()).select_from(Vehicle)
        case Resource.ORDERS_PER_MONTH:
            month_start = (
                select(
                    func.timezone(
                        Workshop.timezone,
                        func.date_trunc(
                            "month", func.timezone(Workshop.timezone, func.now())
                        ),
                    )
                )
                .where(Workshop.id == workshop_id)
                .scalar_subquery()
            )
            query = select(func.count()).where(WorkOrder.created_at >= month_start)
    return int(await session.scalar(query) or 0)
