"""Vehículos del taller activo y su titularidad (RF-11 a RF-13). Los ve todo el
personal; los crea y edita, y les cambia el titular, quien puede hacerlo
(especificación §3)."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.workshop.deps import WorkshopContext, require
from app.domain.permissions import Action
from app.schemas.vehicles import (
    OwnerChange,
    OwnerRead,
    OwnershipRead,
    VehicleCreate,
    VehicleCreated,
    VehicleDetailRead,
    VehicleRead,
    VehicleUpdate,
)
from app.services import vehicles as vehicle_service
from app.services.vehicles import OwnerView, VehicleView

router = APIRouter(prefix="/vehicles")

# Las columnas del vehículo que se devuelven tal cual; el titular va aparte.
COLUMNS = [c for c in VehicleRead.model_fields if c != "owner"]

Viewer = Annotated[WorkshopContext, Depends(require(Action.VIEW_CLIENTS))]
Manager = Annotated[WorkshopContext, Depends(require(Action.MANAGE_CLIENTS))]
OwnerChanger = Annotated[WorkshopContext, Depends(require(Action.CHANGE_VEHICLE_OWNER))]


def _owner(owner: OwnerView) -> OwnerRead:
    return OwnerRead(id=owner.id, name=owner.name)


def _read(view: VehicleView) -> VehicleRead:
    return VehicleRead.model_validate(
        {
            **{c: getattr(view.vehicle, c) for c in COLUMNS},
            "owner": _owner(view.owner) if view.owner else None,
        }
    )


@router.get("")
async def list_vehicles(
    workshop: Viewer,
    q: Annotated[str | None, Query(max_length=100)] = None,
    # Los vehículos de los que este cliente es el titular actual (RF-12).
    owner_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[VehicleRead]:
    views = await vehicle_service.list_vehicles(
        workshop.session, query=q, owner_id=owner_id, limit=limit, offset=offset
    )
    return [_read(view) for view in views]


@router.get("/suggestions")
async def suggestions(
    workshop: Viewer,
    field: Literal["make", "model"],
    q: Annotated[str, Query(max_length=60)] = "",
    make: Annotated[str | None, Query(max_length=60)] = None,
) -> list[str]:
    """Marcas o modelos que el taller ya ha escrito (RF-11)."""
    return await vehicle_service.suggestions(workshop.session, field, q, make)


@router.get("/{vehicle_id}")
async def get_vehicle(vehicle_id: UUID, workshop: Viewer) -> VehicleDetailRead:
    detail = await vehicle_service.get_vehicle(workshop.session, vehicle_id)
    return VehicleDetailRead.model_validate(
        {
            **{c: getattr(detail.vehicle, c) for c in COLUMNS},
            "owner": _owner(detail.owner),
            "ownerships": [
                OwnershipRead(
                    client=_owner(o.client),
                    started_at=o.started_at,
                    ended_at=o.ended_at,
                )
                for o in detail.ownerships
            ],
        }
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_vehicle(body: VehicleCreate, workshop: Manager) -> VehicleCreated:
    vehicle_id = await vehicle_service.create_vehicle(
        workshop.session,
        workshop.workshop_id,
        body.model_dump(exclude={"owner_id"}),
        body.owner_id,
    )
    return VehicleCreated(id=vehicle_id)


@router.patch("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_vehicle(
    vehicle_id: UUID, body: VehicleUpdate, workshop: Manager
) -> None:
    await vehicle_service.update_vehicle(
        workshop.session,
        vehicle_id,
        expected_version=body.version,
        changes=body.model_dump(exclude_unset=True, exclude={"version"}),
    )


@router.post("/{vehicle_id}/owner", status_code=status.HTTP_204_NO_CONTENT)
async def change_owner(
    vehicle_id: UUID, body: OwnerChange, workshop: OwnerChanger
) -> None:
    await vehicle_service.change_owner(
        workshop.session,
        workshop.workshop_id,
        workshop.user_id,
        vehicle_id,
        expected_version=body.version,
        client_id=body.client_id,
    )
