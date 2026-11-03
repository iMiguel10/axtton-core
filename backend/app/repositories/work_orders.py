from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Date,
    Select,
    cast,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased

from app.domain.quotes import QuoteStatus
from app.domain.work_orders import CLOSED, PaymentStatus, WorkOrderStatus
from app.models import (
    Client,
    Employee,
    Quote,
    Vehicle,
    WorkEntry,
    WorkOrder,
    WorkOrderCounter,
    WorkOrderStatusChange,
    Workshop,
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


def _due(due: Literal["overdue", "today", "week", "none"]) -> ColumnElement[bool]:
    expected = WorkOrder.expected_delivery_at
    if due == "none":
        return expected.is_(None)
    if due == "overdue":
        return expected < func.now()
    # El día, en la zona del taller (`workshops.timezone`, que RLS deja leer).
    zone = (
        select(Workshop.timezone)
        .where(Workshop.id == WorkOrder.workshop_id)
        .scalar_subquery()
    )
    day = cast(func.timezone(zone, expected), Date)
    today = cast(func.timezone(zone, func.now()), Date)
    if due == "today":
        return day == today
    return day.between(today, today + 6)


async def list_page(
    session: AsyncSession,
    *,
    statuses: Collection[str] | None,
    responsible_id: UUID | None,
    mine_employee_id: UUID | None,
    vehicle_id: UUID | None,
    client_id: UUID | None,
    due: Literal["overdue", "today", "week", "none"] | None,
    sort: Literal["recent", "stalled", "due"],
    limit: int,
    offset: int,
) -> list[OrderRow]:
    """Órdenes del taller fijado con su vehículo, cliente y responsable (RF-24).

    "recent": las últimas abiertas primero. "stalled": las que llevan más tiempo
    sin actividad primero. "due": la entrega prevista más próxima primero, y las
    que no tienen fecha al final.

    `due` filtra por la fecha prevista: pasada ("overdue"), hoy, en los próximos
    7 días contando hoy ("week") o sin fecha. "Hoy" es el día del taller, no el
    de UTC: a las 00:30 en Madrid, en UTC aún es ayer.
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
    if due is not None:
        statement = statement.where(_due(due))
    order_by: tuple[Any, ...]
    if sort == "stalled":
        order_by = (WorkOrder.last_activity_at, WorkOrder.id)
    elif sort == "due":
        order_by = (WorkOrder.expected_delivery_at.asc().nulls_last(), WorkOrder.id)
    else:
        order_by = (WorkOrder.year.desc(), WorkOrder.number.desc())
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


async def local_date(session: AsyncSession, workshop_id: UUID) -> date:
    """Hoy en la zona horaria del taller: un cobro no puede ser de mañana."""
    today = await session.scalar(
        text(
            "SELECT (clock_timestamp() AT TIME ZONE timezone)::date"
            " FROM workshops WHERE id = :w"
        ),
        {"w": workshop_id},
    )
    assert today is not None
    return today  # type: ignore[no-any-return]


async def unpaid_page(
    session: AsyncSession, *, limit: int, offset: int
) -> list[tuple[OrderRow, int, int | None]]:
    """Las entregadas pendientes de cobro (RF-29), la más antigua primero, con
    los días que lleva pendiente (de la fecha de entrega a hoy, las dos en la
    zona del taller, ix_work_orders_unpaid) y el importe a cobrar.

    El importe es el total guardado de la última versión aprobada, no la suma
    de todas: un trabajo adicional se prepara como versión nueva que copia la
    anterior y le añade lo nuevo, así que sumarlas contaría dos veces lo
    aprobado primero. Si el adicional se rechazó, vale la anterior. Nulo si la
    orden no tuvo presupuesto aprobado ("sin presupuesto", sin reparar).
    """

    def local_day(at: ColumnElement[datetime] | InstrumentedAttribute[Any]) -> Any:
        return func.date(func.timezone(Workshop.timezone, at))

    days = local_day(func.clock_timestamp()) - local_day(WorkOrder.delivered_at)
    approved_total = (
        select(Quote.total_cents)
        .where(
            Quote.work_order_id == WorkOrder.id,
            Quote.status == QuoteStatus.APPROVED,
        )
        .order_by(Quote.version_no.desc())
        .limit(1)
        .scalar_subquery()
    )
    rows = await session.execute(
        _with_context()
        .add_columns(days, approved_total)
        .join(Workshop, Workshop.id == WorkOrder.workshop_id)
        .where(
            WorkOrder.status == WorkOrderStatus.DELIVERED,
            WorkOrder.payment_status == PaymentStatus.PENDING,
        )
        .order_by(WorkOrder.delivered_at, WorkOrder.id)
        .limit(limit)
        .offset(offset)
    )
    return [
        (OrderRow(o, v, c, name), int(d), total) for o, v, c, name, d, total in rows
    ]


async def count_open_for_client(session: AsyncSession, client_id: UUID) -> int:
    """Las órdenes abiertas de un cliente: con alguna, no se le anonimiza."""
    count = await session.scalar(
        select(func.count()).where(
            WorkOrder.client_id == client_id,
            WorkOrder.status.not_in(CLOSED),
        )
    )
    return count or 0


async def forget_dropped_off_by(session: AsyncSession, client_id: UUID) -> None:
    """Al anonimizar (RF-15): quien trajo el coche en sus órdenes es un nombre y
    un teléfono, y no se quedan. Sube la versión: quien tuviera la ficha abierta
    vuelve a cargarla."""
    await session.execute(
        update(WorkOrder)
        .where(
            WorkOrder.client_id == client_id,
            or_(
                WorkOrder.dropped_off_by_name.is_not(None),
                WorkOrder.dropped_off_by_phone.is_not(None),
            ),
        )
        .values(
            dropped_off_by_name=None,
            dropped_off_by_phone=None,
            version=WorkOrder.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
