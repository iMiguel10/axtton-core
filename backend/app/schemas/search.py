from uuid import UUID

from pydantic import BaseModel

from app.schemas.vehicles import OwnerRead


class VehicleHit(BaseModel):
    id: UUID
    plate: str
    make: str | None
    model: str | None
    # Su titular actual: el cliente de la orden que se abra (invariante 7).
    owner: OwnerRead | None


class ClientVehicle(BaseModel):
    id: UUID
    plate: str
    make: str | None
    model: str | None


class ClientHit(BaseModel):
    id: UUID
    name: str
    phone: str
    archived: bool
    # Los vehículos de los que es titular hoy.
    vehicles: list[ClientVehicle]


class SearchRead(BaseModel):
    vehicles: list[VehicleHit]
    clients: list[ClientHit]
