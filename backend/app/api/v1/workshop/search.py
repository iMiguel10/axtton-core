"""La búsqueda única del mostrador (RF-14): matrícula, nombre o teléfono desde una
sola caja. La ve todo el personal (especificación §3)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.v1.workshop.deps import WorkshopContext, require
from app.domain.permissions import Action
from app.schemas.search import ClientHit, ClientVehicle, SearchRead, VehicleHit
from app.schemas.vehicles import OwnerRead
from app.services import search as search_service

router = APIRouter(prefix="/search")

Viewer = Annotated[WorkshopContext, Depends(require(Action.VIEW_CLIENTS))]


@router.get("")
async def search(
    workshop: Viewer, q: Annotated[str, Query(max_length=100)] = ""
) -> SearchRead:
    result = await search_service.search(workshop.session, q)
    return SearchRead(
        vehicles=[
            VehicleHit(
                id=vehicle.id,
                plate=vehicle.plate,
                make=vehicle.make,
                model=vehicle.model,
                owner=OwnerRead(id=owner.id, name=owner.name) if owner else None,
            )
            for vehicle, owner in result.vehicles
        ],
        clients=[
            ClientHit(
                id=hit.client.id,
                name=hit.client.name,
                phone=hit.client.phone,
                archived=hit.client.archived_at is not None,
                vehicles=[
                    ClientVehicle(id=v.id, plate=v.plate, make=v.make, model=v.model)
                    for v in hit.vehicles
                ],
            )
            for hit in result.clients
        ],
    )
