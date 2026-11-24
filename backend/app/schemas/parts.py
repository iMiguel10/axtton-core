"""El catálogo de piezas (F7, RF-90)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.inventory import PART_WARRANTY_MAX_MONTHS, PART_WARRANTY_MIN_MONTHS
from app.domain.quotes import PartCondition

# El mismo tope que una línea de presupuesto: diez millones de euros.
MAX_PRICE_CENTS = 10_000_000_00


class PartRead(BaseModel):
    id: UUID
    reference: str
    description: str
    brand: str | None
    # Nulo si quien mira no puede verlo (especificación §3): el coste, solo el
    # administrador; el de venta, el mecánico si el taller no lo desactiva.
    cost_price_cents: int | None
    sale_price_cents: int | None
    vat_bp: int
    part_condition: PartCondition
    warranty_months: int | None
    tracks_stock: bool
    min_stock: Decimal | None
    archived_at: datetime | None
    created_at: datetime
    # El bloqueo optimista (RNF-15).
    version: int


class PartPage(BaseModel):
    parts: list[PartRead]
    # Si los precios de venta van vacíos porque el taller no deja verlos.
    prices_hidden: bool


class PartCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reference: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=300)
    brand: str | None = Field(default=None, max_length=100)
    cost_price_cents: int | None = Field(default=None, ge=0, le=MAX_PRICE_CENTS)
    sale_price_cents: int = Field(ge=0, le=MAX_PRICE_CENTS)
    # Sin él, el IVA por defecto del taller.
    vat_bp: int | None = Field(default=None, ge=0, le=10_000)
    part_condition: PartCondition = PartCondition.NEW
    warranty_months: int | None = Field(
        default=None, ge=PART_WARRANTY_MIN_MONTHS, le=PART_WARRANTY_MAX_MONTHS
    )
    tracks_stock: bool = True
    min_stock: Decimal | None = Field(
        default=None, ge=0, max_digits=10, decimal_places=3
    )

    @model_validator(mode="after")
    def min_stock_needs_stock(self) -> "PartCreate":
        if self.min_stock is not None and not self.tracks_stock:
            raise ValueError("min_stock sin control de stock")
        return self


class PartCreated(BaseModel):
    id: UUID


class PartUpdate(BaseModel):
    """Solo los campos presentes se cambian (exclude_unset al usarlo)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    version: int
    reference: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=300)
    brand: str | None = Field(default=None, max_length=100)
    cost_price_cents: int | None = Field(default=None, ge=0, le=MAX_PRICE_CENTS)
    sale_price_cents: int | None = Field(default=None, ge=0, le=MAX_PRICE_CENTS)
    vat_bp: int | None = Field(default=None, ge=0, le=10_000)
    part_condition: PartCondition | None = None
    warranty_months: int | None = Field(
        default=None, ge=PART_WARRANTY_MIN_MONTHS, le=PART_WARRANTY_MAX_MONTHS
    )
    tracks_stock: bool | None = None
    min_stock: Decimal | None = Field(
        default=None, ge=0, max_digits=10, decimal_places=3
    )

    @model_validator(mode="after")
    def required_fields_are_not_nulled(self) -> "PartUpdate":
        """Un `null` explícito en un campo obligatorio es un 422, no un 500 de
        la base de datos. Los opcionales (marca, coste, garantía, mínimo) sí se
        pueden vaciar."""
        required = (
            "reference",
            "description",
            "sale_price_cents",
            "vat_bp",
            "part_condition",
            "tracks_stock",
        )
        for field in required:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} no puede ser null")
        return self


class VersionOnly(BaseModel):
    version: int
