"""Clientes del taller activo (RF-10). Los ve todo el personal; los crea y edita
quien puede gestionarlos (especificación §3: el mecánico solo los ve)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.workshop.deps import WorkshopContext, require
from app.domain.permissions import Action
from app.schemas.clients import (
    ClientCreate,
    ClientCreated,
    ClientRead,
    ClientUpdate,
    VersionOnly,
)
from app.services import clients as client_service

router = APIRouter(prefix="/clients")

Viewer = Annotated[WorkshopContext, Depends(require(Action.VIEW_CLIENTS))]
Manager = Annotated[WorkshopContext, Depends(require(Action.MANAGE_CLIENTS))]


@router.get("")
async def list_clients(
    workshop: Viewer,
    q: Annotated[str | None, Query(max_length=100)] = None,
    archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ClientRead]:
    clients = await client_service.list_clients(
        workshop.session, query=q, archived=archived, limit=limit, offset=offset
    )
    return [ClientRead.model_validate(c, from_attributes=True) for c in clients]


@router.get("/{client_id}")
async def get_client(client_id: UUID, workshop: Viewer) -> ClientRead:
    client = await client_service.get_client(workshop.session, client_id)
    return ClientRead.model_validate(client, from_attributes=True)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_client(body: ClientCreate, workshop: Manager) -> ClientCreated:
    client_id = await client_service.create_client(
        workshop.session, workshop.workshop_id, body.model_dump(mode="json")
    )
    return ClientCreated(id=client_id)


@router.patch("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_client(client_id: UUID, body: ClientUpdate, workshop: Manager) -> None:
    await client_service.update_client(
        workshop.session,
        client_id,
        expected_version=body.version,
        changes=body.model_dump(mode="json", exclude_unset=True, exclude={"version"}),
    )


@router.post("/{client_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
async def archive_client(client_id: UUID, body: VersionOnly, workshop: Manager) -> None:
    await client_service.set_archived(
        workshop.session, client_id, expected_version=body.version, archived=True
    )


@router.post("/{client_id}/unarchive", status_code=status.HTTP_204_NO_CONTENT)
async def unarchive_client(
    client_id: UUID, body: VersionOnly, workshop: Manager
) -> None:
    await client_service.set_archived(
        workshop.session, client_id, expected_version=body.version, archived=False
    )
