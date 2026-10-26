"""Órdenes de trabajo: abrirlas, listarlas, editar su recepción y moverlas por su
ciclo de vida (RF-20 a RF-27, especificación §6).

Las reglas de qué transición existe y quién la hace están en domain/work_orders.py;
aquí se aplican con la orden bloqueada. Todo se ejecuta en la transacción del
taller activo (RLS fijada).
"""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)
from app.domain.permissions import Action, can
from app.domain.work_orders import (
    CLOSED,
    NO_QUOTE_STATUSES,
    LastChange,
    NoQuoteReason,
    StatusChangeCause,
    Transition,
    TransitionRefused,
    WorkOrderStatus,
    WorkOrderType,
    allowed_transitions,
    transition_for,
    undo_refusal,
)
from app.models import AuditEntry, WorkOrder, WorkOrderStatusChange
from app.repositories import clients as client_repo
from app.repositories import employees as employee_repo
from app.repositories import vehicles as vehicle_repo
from app.repositories import work_orders as order_repo
from app.repositories import worklog as worklog_repo
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
    # Lo que puede hacer quien la consulta, según su rol y el estado.
    transitions: list[Transition]
    can_undo: bool
    can_mark_no_quote: bool


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
    mine_employee_id: UUID | None,
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
        mine_employee_id=mine_employee_id,
        vehicle_id=vehicle_id,
        client_id=client_id,
        sort=sort,
        limit=limit,
        offset=offset,
    )


async def get_order(session: AsyncSession, order_id: UUID, role: str) -> OrderDetail:
    """La ficha, con lo que `role` puede hacer ahora con ella: así la interfaz
    enseña solo los botones que valen, sin repetir las reglas."""
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
    last = history[-1].change
    undo = (
        undo_refusal(_last(last))
        if can(role, Action.UNDO_STATUS_CHANGE)
        else "not_allowed"
    )
    return OrderDetail(
        row,
        warranty_of,
        history,
        allowed_transitions(
            row.order.status, role, no_quote_reason=row.order.no_quote_reason
        ),
        can_undo=undo is None,
        can_mark_no_quote=can(role, Action.MARK_NO_QUOTE)
        and row.order.status in NO_QUOTE_STATUSES,
    )


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


# --- Ciclo de vida (especificación §6) --------------------------------------

# Cómo llega a la API cada motivo de rechazo del dominio.
_REFUSALS: dict[str, type[AppError]] = {
    "not_allowed": ForbiddenError,
    "note_required": ValidationFailedError,
}


def _refused(code: str) -> AppError:
    return _REFUSALS.get(code, ConflictError)(code)


def _last(change: WorkOrderStatusChange) -> LastChange:
    return LastChange(
        from_status=change.from_status,
        to_status=change.to_status,
        cause=change.cause,
        notified=change.notified,
    )


async def _locked(
    session: AsyncSession, order_id: UUID, expected_version: int
) -> WorkOrder:
    """La orden bloqueada (FOR UPDATE) y con la versión que leyó quien pide el
    cambio. Va antes de leer el último cambio: sin el bloqueo, dos cambios a la
    vez leerían el mismo "último" y el historial ya no diría un solo estado."""
    order = await order_repo.get_for_update(session, order_id)
    if order is None:
        raise NotFoundError("work_order_not_found")
    if order.version != expected_version:
        raise ConflictError("modified_by_someone_else")
    return order


async def _record(
    session: AsyncSession,
    order: WorkOrder,
    to_status: str,
    *,
    cause: StatusChangeCause,
    employee_id: UUID,
    note: str | None = None,
    undoes_seq: int | None = None,
) -> None:
    """Escribe el cambio en el historial y copia el estado en la orden, juntos
    (invariante 5; el trigger diferido lo comprueba al confirmar)."""
    now = await vehicle_repo.db_now(session)
    session.add(
        WorkOrderStatusChange(
            workshop_id=order.workshop_id,
            work_order_id=order.id,
            from_status=order.status,
            to_status=to_status,
            cause=cause,
            employee_id=employee_id,
            note=note,
            undoes_seq=undoes_seq,
        )
    )
    order.status = to_status
    # Un cambio de estado es actividad: la orden deja de estar "parada" (RF-24).
    order.last_activity_at = now
    if to_status == WorkOrderStatus.DELIVERED:
        # De aquí salen la garantía (RF-53) y el plazo de la firma (RF-56).
        order.delivered_at = now
    await session.flush()


async def change_status(
    session: AsyncSession,
    order_id: UUID,
    employee_id: UUID,
    role: str,
    *,
    expected_version: int,
    to_status: str,
    note: str | None,
) -> None:
    """Un cambio de estado hecho a mano (causa `manual`)."""
    order = await _locked(session, order_id, expected_version)
    note = note.strip() if note and note.strip() else None
    try:
        transition = transition_for(
            order.status,
            to_status,
            role,
            no_quote_reason=order.no_quote_reason,
            note=note,
        )
    except TransitionRefused as refused:
        raise _refused(refused.code) from refused
    # Cancelar es solo para órdenes abiertas por error: sin trabajos, piezas
    # usadas ni presupuestos enviados (§6). La orden está bloqueada FOR UPDATE:
    # un trabajo que se esté anotando a la vez espera, y luego la ve cancelada.
    # Las piezas (F7) y los presupuestos (F3) se comprobarán aquí al llegar.
    if (
        transition.to_status == WorkOrderStatus.CANCELLED
        and await worklog_repo.count_active_entries(session, order_id) > 0
    ):
        raise ConflictError("work_order_has_work")
    if transition.unrepaired:
        order.unrepaired = True
    await _record(
        session,
        order,
        transition.to_status,
        cause=StatusChangeCause.MANUAL,
        employee_id=employee_id,
        note=note,
    )


async def undo_last_change(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    employee_id: UUID,
    order_id: UUID,
    *,
    expected_version: int,
) -> None:
    """Deshacer el último cambio manual (§6): un cambio compensatorio que vuelve
    al estado anterior. El original no se borra nunca (RNF-12), y queda en el
    registro de auditoría (RNF-16)."""
    order = await _locked(session, order_id, expected_version)
    last = await order_repo.last_change(session, order_id)
    assert last is not None, "toda orden tiene al menos su apertura"
    refusal = undo_refusal(_last(last))
    if refusal is not None:
        raise ConflictError(refusal)
    assert last.from_status is not None  # un cambio manual viene de algún estado
    if last.to_status == WorkOrderStatus.READY and order.unrepaired:
        # Deshacer "lista · sin reparar" deshace también el "sin reparar".
        order.unrepaired = False
    await _record(
        session,
        order,
        last.from_status,
        cause=StatusChangeCause.UNDO,
        employee_id=employee_id,
        undoes_seq=last.seq,
    )
    session.add(
        AuditEntry(
            workshop_id=workshop_id,
            actor_user_id=user_id,
            action="status_change_undone",
            target_type="work_order",
            target_id=order_id,
            details={"work_order_status": [last.to_status, last.from_status]},
        )
    )


async def set_no_quote(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    order_id: UUID,
    *,
    expected_version: int,
    reason: str | None,
) -> None:
    """Marcar (o desmarcar) una orden "sin presupuesto" (RF-27), antes de
    empezar a repararla. Queda en la auditoría con autor y fecha."""
    order = await _locked(session, order_id, expected_version)
    if order.status not in NO_QUOTE_STATUSES:
        raise ConflictError("no_quote_not_now")
    if reason == NoQuoteReason.WAIVER:
        # La renuncia solo vale firmada en la hoja de recepción (RF-27, RF-52),
        # que llega en F6.
        raise ConflictError("waiver_requires_signed_reception")
    if reason == order.no_quote_reason:
        return
    previous = order.no_quote_reason
    order.no_quote_reason = reason
    session.add(
        AuditEntry(
            workshop_id=workshop_id,
            actor_user_id=user_id,
            action="no_quote_marked",
            target_type="work_order",
            target_id=order_id,
            details={"no_quote_reason": [previous, reason]},
        )
    )
    await session.flush()
