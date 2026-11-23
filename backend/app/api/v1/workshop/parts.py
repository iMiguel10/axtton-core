"""El catálogo de piezas del taller activo (F7, RF-90). Lo consulta todo el
personal; lo da de alta y lo cambia el administrador (especificación §3)."""

from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.workshop.deps import WorkshopContext, require
from app.domain.permissions import Action, can
from app.schemas.parts import (
    PartCreate,
    PartCreated,
    PartPage,
    PartRead,
    PartUpdate,
    VersionOnly,
)
from app.services import parts as part_service

router = APIRouter(prefix="/parts")

Viewer = Annotated[WorkshopContext, Depends(require(Action.VIEW_PARTS))]
Manager = Annotated[WorkshopContext, Depends(require(Action.MANAGE_PARTS))]


@router.get("")
async def list_parts(
    workshop: Viewer,
    q: Annotated[str | None, Query(max_length=100)] = None,
    archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PartPage:
    parts, prices_hidden = await part_service.list_parts(
        workshop.session,
        workshop.workshop_id,
        workshop.role,
        show_costs=can(workshop.role, Action.VIEW_COSTS),
        query=q,
        archived=archived,
        limit=limit,
        offset=offset,
    )
    return PartPage(
        parts=[PartRead(**asdict(part)) for part in parts],
        prices_hidden=prices_hidden,
    )


@router.get("/{part_id}")
async def get_part(part_id: UUID, workshop: Viewer) -> PartRead:
    part = await part_service.get_part(
        workshop.session,
        workshop.workshop_id,
        workshop.role,
        part_id,
        show_costs=can(workshop.role, Action.VIEW_COSTS),
    )
    return PartRead(**asdict(part))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_part(body: PartCreate, workshop: Manager) -> PartCreated:
    part_id = await part_service.create_part(
        workshop.session,
        workshop.workshop_id,
        workshop.user_id,
        body.model_dump(),
    )
    return PartCreated(id=part_id)


@router.patch("/{part_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_part(part_id: UUID, body: PartUpdate, workshop: Manager) -> None:
    await part_service.update_part(
        workshop.session,
        workshop.workshop_id,
        workshop.user_id,
        part_id,
        expected_version=body.version,
        changes=body.model_dump(exclude_unset=True, exclude={"version"}),
    )


@router.post("/{part_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
async def archive_part(part_id: UUID, body: VersionOnly, workshop: Manager) -> None:
    await part_service.set_archived(
        workshop.session, part_id, expected_version=body.version, archived=True
    )


@router.post("/{part_id}/unarchive", status_code=status.HTTP_204_NO_CONTENT)
async def unarchive_part(part_id: UUID, body: VersionOnly, workshop: Manager) -> None:
    await part_service.set_archived(
        workshop.session, part_id, expected_version=body.version, archived=False
    )
