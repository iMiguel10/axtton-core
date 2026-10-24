"""Contrato HTTP de los presupuestos de F0.

Pydantic valida la entrada antes de que llegue al service: un precio negativo o
un IVA de 300 % se rechazan con 422 sin escribir nada.
"""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.quotes import Outcome


class QuoteCreate(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    unit_price_cents: int = Field(ge=0)
    vat_bp: int = Field(default=2100, ge=0, le=10_000)


class QuoteCreated(BaseModel):
    quote_id: UUID


class QuoteSent(BaseModel):
    quote_id: UUID
    total_cents: int
    # F0: la API devuelve el enlace para poder probarlo sin email. En F5 el
    # enlace solo viaja por email al cliente y la respuesta no lo incluye.
    approval_url: str


class LineRead(BaseModel):
    description: str
    quantity: Decimal
    unit_price_cents: int
    vat_bp: int
    line_total_cents: int | None


class PortalQuoteRead(BaseModel):
    status: str
    total_cents: int
    lines: list[LineRead]


class DecisionCreate(BaseModel):
    outcome: Outcome
