from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.vehicles import Fuel


class OwnerRead(BaseModel):
    id: UUID
    name: str


class VehicleRead(BaseModel):
    id: UUID
    plate: str
    plate_normalized: str
    vin: str | None
    make: str | None
    model: str | None
    year: int | None
    fuel: Fuel | None
    next_itv_date: date | None
    next_service_date: date | None
    next_service_km: int | None
    # El titular actual: el periodo abierto de su titularidad.
    owner: OwnerRead | None
    # El cliente la devuelve al editar o cambiar el titular (RNF-15).
    version: int


class OwnershipRead(BaseModel):
    client: OwnerRead
    started_at: datetime
    # Nulo: es el titular actual.
    ended_at: datetime | None


class VehicleDetailRead(VehicleRead):
    owner: OwnerRead
    # Todos sus periodos, el más reciente primero (RF-13).
    ownerships: list[OwnershipRead]


class _VehicleFields(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    vin: str | None = Field(default=None, max_length=25)
    make: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=60)
    year: int | None = Field(default=None, ge=1900, le=2100)
    fuel: Fuel | None = None
    next_itv_date: date | None = None
    next_service_date: date | None = None
    next_service_km: int | None = Field(default=None, gt=0)


class VehicleCreate(_VehicleFields):
    # Con espacios o guiones: se normaliza en el servidor.
    plate: str = Field(min_length=1, max_length=20)
    # Un vehículo nace con su titular (RF-12).
    owner_id: UUID


class VehicleCreated(BaseModel):
    id: UUID


class VehicleUpdate(_VehicleFields):
    """Solo los campos presentes se cambian (exclude_unset al usarlo). El
    titular no se cambia aquí: tiene su propia operación."""

    version: int
    plate: str | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def plate_is_not_nulled(self) -> "VehicleUpdate":
        if "plate" in self.model_fields_set and self.plate is None:
            raise ValueError("plate no puede ser null")
        return self


class OwnerChange(BaseModel):
    version: int
    client_id: UUID
