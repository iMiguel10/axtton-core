from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Select, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (
    Client,
    Employee,
    Vehicle,
    WorkEntry,
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
    mine_employee_id: UUID | None,
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
    if mine_employee_id is not None:
        # "Mis órdenes" (RF-24): de las que soy responsable o en las que he
        # registrado trabajo (sin anular).
        worked = (
            select(WorkEntry.id)
            .where(
                WorkEntry.work_order_id == WorkOrder.id,
                WorkEntry.employee_id == mine_employee_id,
                WorkEntry.voided_at.is_(None),
            )
            .exists()
        )
        statement = statement.where(
            or_(WorkOrder.responsible_employee_id == mine_employee_id, worked)
        )
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


async def get_for_update(session: AsyncSession, order_id: UUID) -> WorkOrder | None:
    """La orden, bloqueada hasta el final de la transacción (arquitectura §3).

    Todo cambio de estado pasa por aquí antes de leer el último cambio: dos
    cambios a la vez sobre la misma orden se ponen en fila, y el segundo ve ya
    el estado y la versión que dejó el primero.
    """
    query = (
        select(WorkOrder)
        .where(WorkOrder.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(query)).one_or_none()


async def last_change(
    session: AsyncSession, order_id: UUID
) -> WorkOrderStatusChange | None:
    """El cambio con el `seq` más alto: el que dice el estado (invariante 5)."""
    query = (
        select(WorkOrderStatusChange)
        .where(WorkOrderStatusChange.work_order_id == order_id)
        .order_by(WorkOrderStatusChange.seq.desc())
        .limit(1)
    )
    return (await session.scalars(query)).one_or_none()


async def get_for_share(session: AsyncSession, order_id: UUID) -> WorkOrder | None:
    """La orden, con un bloqueo compartido hasta el final de la transacción.

    Para escribir en ella sin cambiar su estado (diagnóstico, trabajos): varias
    escrituras así no se esperan entre sí, pero un cambio de estado (que pide
    FOR UPDATE) sí espera a que terminen, y ellas a él. Así, un trabajo no se
    cuela en una orden que alguien está cancelando o entregando.
    """
    query = (
        select(WorkOrder)
        .where(WorkOrder.id == order_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(query)).one_or_none()


async def get_for_activity(session: AsyncSession, order_id: UUID) -> WorkOrder | None:
    """La orden, bloqueada FOR NO KEY UPDATE, para lo que además de escribir en
    ella actualiza su `last_activity_at` (registrar un trabajo).

    No FOR SHARE: dos trabajos a la vez tendrían cada uno su bloqueo compartido
    y esperarían al del otro para actualizar la orden, un interbloqueo. Este
    bloqueo los pone en fila entre sí y frente a un cambio de estado, y no
    molesta a quien solo lee ni a las FK que apuntan a la orden.
    """
    query = (
        select(WorkOrder)
        .where(WorkOrder.id == order_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(query)).one_or_none()
