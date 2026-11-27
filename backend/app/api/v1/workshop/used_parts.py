"""Las piezas usadas en una orden (F7 paso 3, RF-93). Las ve todo el personal;
las anotan los dos roles (especificación §3)."""

from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.v1.workshop.deps import WorkshopContext, require
from app.domain.permissions import Action
from app.schemas.used_parts import UsedPartCreate, UsedPartCreated, UsedPartRead
from app.services import used_parts as used_part_service

router = APIRouter(prefix="/orders/{order_id}/used-parts")

Viewer = Annotated[WorkshopContext, Depends(require(Action.VIEW_ORDERS))]
Recorder = Annotated[WorkshopContext, Depends(require(Action.RECORD_USED_PARTS))]


@router.get("")
async def list_used_parts(order_id: UUID, workshop: Viewer) -> list[UsedPartRead]:
    used = await used_part_service.list_for_order(
        workshop.session, workshop.employee_id, workshop.role, order_id
    )
    return [UsedPartRead(**asdict(part)) for part in used]


@router.post("", status_code=status.HTTP_201_CREATED)
async def mount_part(
    order_id: UUID, body: UsedPartCreate, workshop: Recorder
) -> UsedPartCreated:
    used_id = await used_part_service.mount(
        workshop.session,
        workshop.workshop_id,
        workshop.employee_id,
        order_id,
        part_id=body.part_id,
        quantity=body.quantity,
    )
    return UsedPartCreated(id=used_id)


@router.post("/{used_part_id}/remove", status_code=status.HTTP_204_NO_CONTENT)
async def remove_part(order_id: UUID, used_part_id: UUID, workshop: Recorder) -> None:
    await used_part_service.remove(
        workshop.session, workshop.employee_id, workshop.role, order_id, used_part_id
    )
