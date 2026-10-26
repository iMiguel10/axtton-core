from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Select, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (
    Client,
    Employee,
    Vehicle,
    WorkOrder,
    WorkOrderCounter,
    WorkOrderStatusChange,
)


async def local_year(
    session: AsyncSession, workshop_id: UUID, at: datetime | None = None
) -> int:
    """El año en la zona horaria del taller (`workshops.timezone`), ahora o en
    `at`. Una orden abierta en Madrid el 1 de enero a las 00:30 es del año
    nuevo, aunque en UTC aún sea 31 de diciembre."""
    year = await session.scalar(
        text(
            "SELECT extract(year FROM"
            " coalesce(CAST(:at AS timestamptz), clock_timestamp())"
            " AT TIME ZONE timezone)::int FROM workshops WHERE id = :w"
        ),
        {"at": at, "w": workshop_id},
    )
    assert year is not None
    return int(year)


async def next_number(session: AsyncSession, workshop_id: UUID, year: int) -> int:
    """El siguiente número de orden del taller en ese año (RF-21).

    Una sola sentencia: crea el contador del año con 1, o lo sube en uno si ya
    existe, y devuelve el resultado. La fila queda bloqueada hasta el final de
    la transacción, así que dos aperturas a la vez se ponen en fila aquí y nunca
    reciben el mismo número. Si la transacción se deshace, el número se pierde
    (un hueco): para una orden, que no es una factura, es aceptable.
    """
    statement = (
        insert(WorkOrderCounter)
        .values(workshop_id=workshop_id, year=year, last_number=1)
        .on_conflict_do_update(
            index_elements=["workshop_id", "year"],
            set_={"last_number": WorkOrderCounter.last_number + 1},
        )
        .returning(WorkOrderCounter.last_number)
    )
    number = await session.scalar(statement)
    assert number is not None
    return number


async def get(session: AsyncSession, order_id: UUID) -> WorkOrder | None:
    return await session.get(WorkOrder, order_id)


@dataclass(frozen=True)
class OrderRow:
    order: WorkOrder
    vehicle: Vehicle
    client: Client
    responsible_name: str | None


def _with_context() -> Select[WorkOrder, Vehicle, Client, str]:
    responsible = aliased(Employee)
    return (
        select(WorkOrder, Vehicle, Client, responsible.name)
        .join(Vehicle, Vehicle.id == WorkOrder.vehicle_id)
        .join(Client, Client.id == WorkOrder.client_id)
        .outerjoin(responsible, responsible.id == WorkOrder.responsible_employee_id)
    )


async def get_row(session: AsyncSession, order_id: UUID) -> OrderRow | None:
    row = (
        await session.execute(_with_context().where(WorkOrder.id == order_id))
    ).one_or_none()
    if row is None:
        return None
    order, vehicle, client, responsible_name = row
    return OrderRow(order, vehicle, client, responsible_name)


async def list_page(
    session: AsyncSession,
    *,
    statuses: Collection[str] | None,
    responsible_id: UUID | None,
    vehicle_id: UUID | None,
    client_id: UUID | None,
    sort: Literal["recent", "stalled"],
    limit: int,
    offset: int,
) -> list[OrderRow]:
    """Órdenes del taller fijado con su vehículo, cliente y responsable (RF-24).

    "recent": las últimas abiertas primero. "stalled": las que llevan más tiempo
    sin actividad primero.
    """
    statement = _with_context()
    if statuses is not None:
        statement = statement.where(WorkOrder.status.in_(statuses))
    if responsible_id is not None:
        statement = statement.where(WorkOrder.responsible_employee_id == responsible_id)
    if vehicle_id is not None:
        statement = statement.where(WorkOrder.vehicle_id == vehicle_id)
    if client_id is not None:
        statement = statement.where(WorkOrder.client_id == client_id)
    order_by = (
        (WorkOrder.last_activity_at, WorkOrder.id)
        if sort == "stalled"
        else (WorkOrder.year.desc(), WorkOrder.number.desc())
    )
    rows = await session.execute(
        statement.order_by(*order_by).limit(limit).offset(offset)
    )
    return [OrderRow(o, v, c, name) for o, v, c, name in rows]


async def history(
    session: AsyncSession, order_id: UUID
) -> list[tuple[WorkOrderStatusChange, str | None]]:
    """El historial de estados por `seq`, nunca por fecha, con quién lo hizo."""
    rows = await session.execute(
        select(WorkOrderStatusChange, Employee.name)
        .outerjoin(Employee, Employee.id == WorkOrderStatusChange.employee_id)
        .where(WorkOrderStatusChange.work_order_id == order_id)
        .order_by(WorkOrderStatusChange.seq)
    )
    return [(change, name) for change, name in rows]
