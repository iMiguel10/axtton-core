"""Órdenes de trabajo: abrirlas, listarlas y editar su recepción (RF-20 a RF-25).

Los cambios de estado, cancelar, entregar y deshacer llegan en el paso 4 de F2.
Todo se ejecuta en la transacción del taller activo (RLS fijada).
"""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.domain.work_orders import (
    CLOSED,
    StatusChangeCause,
    WorkOrderStatus,
    WorkOrderType,
)
from app.models import WorkOrder, WorkOrderStatusChange
from app.repositories import clients as client_repo
from app.repositories import employees as employee_repo
from app.repositories import vehicles as vehicle_repo
from app.repositories import work_orders as order_repo
from app.repositories.work_orders import OrderRow

# Lo que se puede cambiar con PATCH: los datos de recepción y el responsable.
# El tipo, el vehículo y el cliente quedan fijados al abrir.
EDITABLE = (
    "odometer_km",
    "reason",
    "expected_delivery_at",
    "dropped_off_by_name",
    "dropped_off_by_phone",
    "reception_notes",
    "responsible_employee_id",
)
OPTIONAL_TEXT = (
    "reason",
    "dropped_off_by_name",
    "dropped_off_by_phone",
    "reception_notes",
)


@dataclass(frozen=True)
class HistoryEntry:
    change: WorkOrderStatusChange
    employee_name: str | None


@dataclass(frozen=True)
class OrderDetail:
    row: OrderRow
    warranty_of: WorkOrder | None
    history: list[HistoryEntry]


def _blank_to_none(values: dict[str, Any]) -> dict[str, Any]:
    result = dict(values)
    for field in OPTIONAL_TEXT:
        if field in result and not result[field]:
            result[field] = None
    return result


async def _check_responsible(session: AsyncSession, employee_id: UUID | None) -> None:
    """El responsable es una ficha activa de este taller (RF-25). Puede no tener
    acceso a la aplicación: un mecánico que nunca la toca existe igual."""
    if employee_id is None:
        return
    employee = await employee_repo.get(session, employee_id)
    if employee is None or not employee.active:
        raise NotFoundError("employee_not_found")


async def _check_warranty_of(
    session: AsyncSession, vehicle_id: UUID, type_: str, warranty_of_id: UUID | None
) -> None:
    """Una orden de garantía puede enlazar a la orden original, que es del mismo
    vehículo y ya se entregó: una entregada no se reabre nunca (§6)."""
    if warranty_of_id is None:
        return
    if type_ != WorkOrderType.WARRANTY:
        raise ValidationFailedError("warranty_of_requires_warranty_type")
    original = await order_repo.get(session, warranty_of_id)
    if original is None or original.vehicle_id != vehicle_id:
        raise NotFoundError("work_order_not_found")
    if original.status != WorkOrderStatus.DELIVERED:
        raise ConflictError("warranty_of_not_delivered")


async def open_order(
    session: AsyncSession,
    workshop_id: UUID,
    employee_id: UUID,
    *,
    vehicle_id: UUID,
    type_: str,
    warranty_of_id: UUID | None,
    fields: dict[str, Any],
) -> WorkOrder:
    """Abrir una orden para un vehículo (RF-20).

    Su cliente es el titular de ese momento y no se elige (invariante 7). Nace en
    `received`, con su primer cambio en el historial, para que el estado sea
    siempre el del último cambio (invariante 5).
    """
    vehicle = await vehicle_repo.get_for_share(session, vehicle_id)
    if vehicle is None:
        raise NotFoundError("vehicle_not_found")
    ownership = await vehicle_repo.current_ownership(session, vehicle_id)
    assert ownership is not None, "un vehículo siempre tiene titular"
    client = await client_repo.get(session, ownership.client_id)
    assert client is not None
    if client.archived_at is not None:
        raise ConflictError("client_archived")
    values = _blank_to_none(fields)
    await _check_responsible(session, values.get("responsible_employee_id"))
    await _check_warranty_of(session, vehicle_id, type_, warranty_of_id)

    year = await order_repo.local_year(session, workshop_id)
    number = await order_repo.next_number(session, workshop_id, year)
    now = await vehicle_repo.db_now(session)
    order = WorkOrder(
        workshop_id=workshop_id,
        year=year,
        number=number,
        type=type_,
        vehicle_id=vehicle_id,
        client_id=client.id,
        warranty_of_id=warranty_of_id,
        status=WorkOrderStatus.RECEIVED,
        last_activity_at=now,
        **values,
    )
    session.add(order)
    await session.flush()
    session.add(
        WorkOrderStatusChange(
            workshop_id=workshop_id,
            work_order_id=order.id,
            from_status=None,
            to_status=WorkOrderStatus.RECEIVED,
            cause=StatusChangeCause.OPENED,
            employee_id=employee_id,
        )
    )
    await session.flush()
    return order


async def list_orders(
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
    return await order_repo.list_page(
        session,
        statuses=statuses,
        responsible_id=responsible_id,
        vehicle_id=vehicle_id,
        client_id=client_id,
        sort=sort,
        limit=limit,
        offset=offset,
    )


async def get_order(session: AsyncSession, order_id: UUID) -> OrderDetail:
    row = await order_repo.get_row(session, order_id)
    if row is None:
        raise NotFoundError("work_order_not_found")
    warranty_of = (
        await order_repo.get(session, row.order.warranty_of_id)
        if row.order.warranty_of_id
        else None
    )
    history = [
        HistoryEntry(change, name)
        for change, name in await order_repo.history(session, order_id)
    ]
    return OrderDetail(row, warranty_of, history)


async def update_order(
    session: AsyncSession,
    order_id: UUID,
    *,
    expected_version: int,
    changes: dict[str, Any],
) -> None:
    """Editar la recepción o el responsable (RF-20, RF-25), con bloqueo
    optimista (RNF-15). Una orden cerrada no se edita (RF-26)."""
    order = await order_repo.get(session, order_id)
    if order is None:
        raise NotFoundError("work_order_not_found")
    if order.version != expected_version:
        raise ConflictError("modified_by_someone_else")
    if order.status in CLOSED:
        raise ConflictError("work_order_closed")
    values = _blank_to_none(changes)
    if "responsible_employee_id" in values:
        await _check_responsible(session, values["responsible_employee_id"])
    for field in EDITABLE:
        if field in values:
            setattr(order, field, values[field])
    await session.flush()
