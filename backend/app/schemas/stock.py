"""El libro de movimientos de stock (F7 paso 2, RF-91 a RF-96)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.inventory import MAX_QUANTITY, MovementKind
from app.schemas.parts import MAX_PRICE_CENTS

# Cantidades de numeric(10,3): litros de aceite (arquitectura §3).
Positive = Field(gt=0, le=MAX_QUANTITY, max_digits=10, decimal_places=3)


class EntryCreate(BaseModel):
    """Llega mercancía (RF-91)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    quantity: Decimal = Positive
    unit_cost_cents: int = Field(ge=0, le=MAX_PRICE_CENTS)
    note: str | None = Field(default=None, max_length=500)


class AdjustmentCreate(BaseModel):
    """Rotura, pérdida o lo que apareció (RF-92): de cualquier signo, nunca 0, y
    con su motivo."""

    model_config = ConfigDict(str_strip_whitespace=True)

    quantity: Decimal = Field(
        ge=-MAX_QUANTITY, le=MAX_QUANTITY, max_digits=10, decimal_places=3
    )
    note: str = Field(min_length=1, max_length=500)

    @field_validator("quantity")
    @classmethod
    def not_zero(cls, value: Decimal) -> Decimal:
        if value == 0:
            raise ValueError("un ajuste de 0 no ajusta nada")
        return value


class CountCreate(BaseModel):
    """Un recuento (RF-92): lo contado y el stock que se veía al contar."""

    model_config = ConfigDict(str_strip_whitespace=True)

    counted: Decimal = Field(ge=0, le=MAX_QUANTITY, max_digits=10, decimal_places=3)
    expected: Decimal = Field(
        ge=-MAX_QUANTITY, le=MAX_QUANTITY, max_digits=13, decimal_places=3
    )
    note: str | None = Field(default=None, max_length=500)


class ReversalCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    note: str = Field(min_length=1, max_length=500)


class MovementCreated(BaseModel):
    # Nulo si un recuento coincidió con el stock: no se anota nada.
    id: UUID | None


class MovementRead(BaseModel):
    id: UUID
    seq: int
    kind: MovementKind
    quantity: Decimal
    unit_cost_cents: int | None
    note: str | None
    counted_stock: Decimal | None
    reverses_id: UUID | None
    reversed_by_id: UUID | None
    employee_name: str
    created_at: datetime


class MovementPage(BaseModel):
    movements: list[MovementRead]
    # El `before` de la página siguiente; nulo si no hay más.
    next_before: int | None
