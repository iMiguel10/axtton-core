"""Órdenes de trabajo del taller activo (RF-20 a RF-27, especificación §6).

Todo el personal las ve. Abrirlas, editar su recepción o su responsable,
deshacer y marcar "sin presupuesto" es del administrador; los cambios de estado,
de quien permita cada transición (especificación §3)."""

from collections.abc import Collection
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.workshop.deps import WorkshopContext, require
from app.domain.permissions import Action
from app.domain.work_orders import CLOSED, OPEN, WorkOrderStatus, order_code
from app.repositories.work_orders import OrderRow
from app.schemas.work_orders import (
    Named,
    NoQuoteChange,
    OrderClient,
    OrderRef,
    OrderVehicle,
    StatusChange,
    StatusChangeRead,
    TransitionRead,
    VersionOnly,
    WorkOrderCreate,
    WorkOrderCreated,
    WorkOrderDetailRead,
    WorkOrderRead,
    WorkOrderUpdate,
)
from app.services import work_orders as order_service

router = APIRouter(prefix="/orders")

Viewer = Annotated[WorkshopContext, Depends(require(Action.VIEW_ORDERS))]
Manager = Annotated[WorkshopContext, Depends(require(Action.MANAGE_ORDERS))]
Undoer = Annotated[WorkshopContext, Depends(require(Action.UNDO_STATUS_CHANGE))]
NoQuoteMarker = Annotated[WorkshopContext, Depends(require(Action.MARK_NO_QUOTE))]

STATES = {"open": OPEN, "closed": CLOSED, "all": None}


def _summary(row: OrderRow) -> dict[str, object]:
    order = row.order
    return {
        "id": order.id,
        "code": order_code(order.year, order.number),
        "year": order.year,
        "number": order.number,
        "type": order.type,
        "status": order.status,
        "unrepaired": order.unrepaired,
        "vehicle": OrderVehicle(
            id=row.vehicle.id,
            plate=row.vehicle.plate,
            make=row.vehicle.make,
            model=row.vehicle.model,
        ),
        "client": OrderClient(
            id=row.client.id, name=row.client.name, phone=row.client.phone
        ),
        "responsible": (
            Named(id=order.responsible_employee_id, name=row.responsible_name)
            if order.responsible_employee_id and row.responsible_name
            else None
        ),
        "expected_delivery_at": order.expected_delivery_at,
        "last_activity_at": order.last_activity_at,
        "created_at": order.created_at,
        "version": order.version,
    }


@router.get("")
async def list_orders(
    workshop: Viewer,
    state: Literal["open", "closed", "all"] = "open",
    # Dentro del estado elegido, solo estos (p. ej. ?status=ready).
    status_: Annotated[list[WorkOrderStatus] | None, Query(alias="status")] = None,
    responsible_id: UUID | None = None,
    # "Mis órdenes" (RF-24): las que tengo como responsable. Las órdenes en las
    # que he registrado trabajo se añadirán con los trabajos (paso 5 de F2).
    mine: bool = False,
    vehicle_id: UUID | None = None,
    client_id: UUID | None = None,
    sort: Literal["recent", "stalled"] = "recent",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[WorkOrderRead]:
    in_state = STATES[state]
    statuses: Collection[str] | None = in_state
    if status_:
        wanted = {s.value for s in status_}
        statuses = wanted if in_state is None else wanted & in_state
    rows = await order_service.list_orders(
        workshop.session,
        statuses=statuses,
        responsible_id=workshop.employee_id if mine else responsible_id,
        vehicle_id=vehicle_id,
        client_id=client_id,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return [WorkOrderRead.model_validate(_summary(row)) for row in rows]


@router.get("/{order_id}")
async def get_order(order_id: UUID, workshop: Viewer) -> WorkOrderDetailRead:
    detail = await order_service.get_order(workshop.session, order_id, workshop.role)
    order = detail.row.order
    warranty_of = detail.warranty_of
    return WorkOrderDetailRead.model_validate(
        {
            **_summary(detail.row),
            "no_quote_reason": order.no_quote_reason,
            "warranty_of": (
                OrderRef(
                    id=warranty_of.id,
                    code=order_code(warranty_of.year, warranty_of.number),
                )
                if warranty_of
                else None
            ),
            "odometer_km": order.odometer_km,
            "reason": order.reason,
            "dropped_off_by_name": order.dropped_off_by_name,
            "dropped_off_by_phone": order.dropped_off_by_phone,
            "reception_notes": order.reception_notes,
            "delivered_at": order.delivered_at,
            "history": [
                StatusChangeRead(
                    seq=entry.change.seq,
                    from_status=entry.change.from_status,
                    to_status=entry.change.to_status,
                    cause=entry.change.cause,
                    undoes_seq=entry.change.undoes_seq,
                    employee_name=entry.employee_name,
                    by_client=entry.change.by_client,
                    note=entry.change.note,
                    created_at=entry.change.created_at,
                )
                for entry in detail.history
            ],
            "allowed_transitions": [
                TransitionRead(
                    to_status=t.to_status,
                    needs_note=t.needs_note,
                    unrepaired=t.unrepaired,
                )
                for t in detail.transitions
            ],
            "can_undo": detail.can_undo,
            "can_mark_no_quote": detail.can_mark_no_quote,
        }
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def open_order(body: WorkOrderCreate, workshop: Manager) -> WorkOrderCreated:
    order = await order_service.open_order(
        workshop.session,
        workshop.workshop_id,
        workshop.employee_id,
        vehicle_id=body.vehicle_id,
        type_=body.type.value,
        warranty_of_id=body.warranty_of_id,
        fields=body.model_dump(exclude={"vehicle_id", "type", "warranty_of_id"}),
    )
    return WorkOrderCreated(id=order.id, code=order_code(order.year, order.number))


@router.patch("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_order(
    order_id: UUID, body: WorkOrderUpdate, workshop: Manager
) -> None:
    await order_service.update_order(
        workshop.session,
        order_id,
        expected_version=body.version,
        changes=body.model_dump(exclude_unset=True, exclude={"version"}),
    )


@router.post("/{order_id}/status", status_code=status.HTTP_204_NO_CONTENT)
async def change_status(order_id: UUID, body: StatusChange, workshop: Viewer) -> None:
    """Un cambio de estado a mano (§6). Lo puede pedir todo el personal: qué
    transición permite cada rol lo decide domain.transition_for (RNF-03)."""
    await order_service.change_status(
        workshop.session,
        order_id,
        workshop.employee_id,
        workshop.role,
        expected_version=body.version,
        to_status=body.to_status.value,
        note=body.note,
    )


@router.post("/{order_id}/undo", status_code=status.HTTP_204_NO_CONTENT)
async def undo_last_change(order_id: UUID, body: VersionOnly, workshop: Undoer) -> None:
    await order_service.undo_last_change(
        workshop.session,
        workshop.workshop_id,
        workshop.user_id,
        workshop.employee_id,
        order_id,
        expected_version=body.version,
    )


@router.post("/{order_id}/no-quote", status_code=status.HTTP_204_NO_CONTENT)
async def set_no_quote(
    order_id: UUID, body: NoQuoteChange, workshop: NoQuoteMarker
) -> None:
    await order_service.set_no_quote(
        workshop.session,
        workshop.workshop_id,
        workshop.user_id,
        order_id,
        expected_version=body.version,
        reason=body.reason.value if body.reason else None,
    )
