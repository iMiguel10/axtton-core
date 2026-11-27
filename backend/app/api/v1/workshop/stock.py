"""El stock de las piezas del taller activo (F7 paso 2, RF-91 a RF-96). Lo
consulta todo el personal; las entradas, los ajustes, los recuentos y sus
anulaciones son del administrador (especificación §3)."""

from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.workshop.deps import WorkshopContext, require
from app.domain.permissions import Action, can
from app.schemas.stock import (
    AdjustmentCreate,
    CountCreate,
    EntryCreate,
    MovementCreated,
    MovementPage,
    MovementRead,
    ReversalCreate,
)
from app.services import stock as stock_service

router = APIRouter()

Viewer = Annotated[WorkshopContext, Depends(require(Action.VIEW_PARTS))]
Manager = Annotated[WorkshopContext, Depends(require(Action.MANAGE_STOCK))]


@router.get("/parts/{part_id}/movements")
async def list_movements(
    part_id: UUID,
    workshop: Viewer,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> MovementPage:
    movements = await stock_service.history(
        workshop.session,
        part_id,
        show_costs=can(workshop.role, Action.VIEW_COSTS),
        before_seq=before,
        limit=limit,
    )
    return MovementPage(
        movements=[MovementRead(**asdict(m)) for m in movements],
        next_before=movements[-1].seq if len(movements) == limit else None,
    )


@router.post("/parts/{part_id}/stock/entries", status_code=status.HTTP_201_CREATED)
async def record_entry(
    part_id: UUID, body: EntryCreate, workshop: Manager
) -> MovementCreated:
    movement_id = await stock_service.record_entry(
        workshop.session,
        workshop.workshop_id,
        workshop.employee_id,
        part_id,
        quantity=body.quantity,
        unit_cost_cents=body.unit_cost_cents,
        note=body.note,
    )
    return MovementCreated(id=movement_id)


@router.post("/parts/{part_id}/stock/adjustments", status_code=status.HTTP_201_CREATED)
async def record_adjustment(
    part_id: UUID, body: AdjustmentCreate, workshop: Manager
) -> MovementCreated:
    movement_id = await stock_service.record_adjustment(
        workshop.session,
        workshop.workshop_id,
        workshop.employee_id,
        part_id,
        quantity=body.quantity,
        note=body.note,
    )
    return MovementCreated(id=movement_id)


@router.post("/parts/{part_id}/stock/count")
async def record_count(
    part_id: UUID, body: CountCreate, workshop: Manager
) -> MovementCreated:
    movement_id = await stock_service.record_count(
        workshop.session,
        workshop.workshop_id,
        workshop.employee_id,
        part_id,
        counted=body.counted,
        expected=body.expected,
        note=body.note,
    )
    return MovementCreated(id=movement_id)


@router.post(
    "/stock-movements/{movement_id}/reverse", status_code=status.HTTP_201_CREATED
)
async def reverse_movement(
    movement_id: UUID, body: ReversalCreate, workshop: Manager
) -> MovementCreated:
    reversal_id = await stock_service.reverse(
        workshop.session,
        workshop.workshop_id,
        workshop.employee_id,
        movement_id,
        note=body.note,
    )
    return MovementCreated(id=reversal_id)
