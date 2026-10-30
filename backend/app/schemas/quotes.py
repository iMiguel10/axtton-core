from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.quotes import (
    MAX_LINES_PER_VERSION,
    DiscountKind,
    LineKind,
    PartCondition,
    QuoteStatus,
)


class VatGroupRead(BaseModel):
    vat_bp: int
    base_cents: int
    vat_cents: int


class QuoteTotalsRead(BaseModel):
    subtotal_cents: int
    global_discount_cents: int
    vat_breakdown: list[VatGroupRead]
    total_cents: int


class QuoteLineRead(BaseModel):
    id: UUID
    position: int
    kind: LineKind
    description: str
    reference: str | None
    part_condition: PartCondition | None
    quantity: Decimal
    # Nulos si quien mira no puede ver importes (especificación §3).
    unit_price_cents: int | None
    discount_bp: int
    vat_bp: int
    # Base imponible y total de la línea: guardados si la versión se envió, o
    # calculados al leer si es un borrador.
    taxable_cents: int | None
    total_cents: int | None


class QuoteRead(BaseModel):
    id: UUID
    version_no: int
    status: QuoteStatus
    created_at: datetime
    sent_at: datetime | None
    valid_until: datetime | None
    cancel_reason: str | None
    global_discount_kind: DiscountKind | None
    global_discount_value: int | None
    lines: list[QuoteLineRead]
    # Nulo si quien mira no puede ver importes. En un borrador, es lo que
    # saldría si se enviara ahora: no se guarda hasta enviarlo.
    totals: QuoteTotalsRead | None
    prices_hidden: bool
    # Bloqueo optimista (RNF-15): se devuelve al guardar el borrador.
    version: int


class QuoteCreated(BaseModel):
    id: UUID


class QuoteLineInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    kind: LineKind
    description: str = Field(min_length=1, max_length=500)
    reference: str | None = Field(default=None, max_length=100)
    part_condition: PartCondition | None = None
    # numeric(10,3): positiva, con tres decimales como mucho.
    quantity: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    unit_price_cents: int = Field(ge=0, le=10_000_000_00)
    discount_bp: int = Field(default=0, ge=0, le=10_000)
    vat_bp: int = Field(ge=0, le=10_000)

    @model_validator(mode="after")
    def condition_only_for_parts(self) -> "QuoteLineInput":
        """RF-38: toda pieza dice si es nueva, usada, reacondicionada o no
        específica; las demás líneas no lo dicen. Una pieza sin decirlo es
        nueva."""
        if self.kind == LineKind.PART and self.part_condition is None:
            self.part_condition = PartCondition.NEW
        if self.kind != LineKind.PART and self.part_condition is not None:
            raise ValueError("part_condition solo en las piezas")
        return self


class GlobalDiscountInput(BaseModel):
    kind: DiscountKind
    # Puntos básicos si es porcentaje; céntimos si es importe.
    value: int = Field(ge=0)

    @model_validator(mode="after")
    def percent_up_to_100(self) -> "GlobalDiscountInput":
        if self.kind == DiscountKind.PERCENT and self.value > 10_000:
            raise ValueError("un porcentaje no pasa de 100")
        return self


class QuoteDraftSave(BaseModel):
    """El borrador entero: guardar reemplaza sus líneas y su descuento global."""

    version: int
    global_discount: GlobalDiscountInput | None = None
    lines: list[QuoteLineInput] = Field(max_length=MAX_LINES_PER_VERSION)


class QuoteSaved(BaseModel):
    version: int
