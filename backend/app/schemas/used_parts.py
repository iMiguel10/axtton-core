"""Las piezas usadas en una orden (F7 paso 3, RF-93)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.inventory import MAX_QUANTITY
from app.domain.quotes import PartCondition


class UsedPartCreate(BaseModel):
    part_id: UUID
    # Litros de aceite: tres decimales (arquitectura §3).
    quantity: Decimal = Field(gt=0, le=MAX_QUANTITY, max_digits=10, decimal_places=3)


class UsedPartCreated(BaseModel):
    id: UUID


class UsedPartRead(BaseModel):
    id: UUID
    part_id: UUID
    # Copiados de la pieza al montarla.
    reference: str
    description: str
    part_condition: PartCondition
    warranty_months: int | None
    quantity: Decimal
    employee_id: UUID
    employee_name: str
    created_at: datetime
    removed_at: datetime | None
    removed_by_name: str | None
    removable: bool
