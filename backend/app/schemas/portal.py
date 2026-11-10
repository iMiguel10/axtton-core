from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.domain.portal import ClientOrderStatus
from app.domain.quotes import (
    DecisionChannel,
    LineKind,
    Outcome,
    PartCondition,
    QuoteStatus,
)
from app.schemas.session import WhoAmI


class PortalEntryRead(BaseModel):
    workshop_name: str


class PortalLinkRequest(BaseModel):
    # El taller de la página de entrada: el enlace solo será de ese taller.
    workshop_id: UUID
    email: EmailStr


class PortalLinkConsume(BaseModel):
    workshop_id: UUID
    # Los de core/tokens.py tienen 43 caracteres; el tope solo evita cuerpos
    # absurdos antes de calcular el hash.
    token: str = Field(min_length=1, max_length=100)


class PortalMe(WhoAmI):
    workshop_id: UUID
    workshop_name: str
    # IANA: las fechas del portal se enseñan en la zona del taller.
    timezone: str
    client_name: str
    language: str


class _FromView(BaseModel):
    """Se rellena desde lo que devuelve el service. Lo que no esté aquí no sale."""

    model_config = ConfigDict(from_attributes=True)


class PortalProgress(_FromView):
    status: ClientOrderStatus
    updated_at: datetime
    expected_delivery_at: datetime | None
    delivery_overdue: bool


class PortalOrderSummary(_FromView):
    id: UUID
    # OT-2026-0042 (RF-21).
    code: str
    opened_at: datetime
    progress: PortalProgress


class PortalVehicleInfo(_FromView):
    plate: str
    make: str | None
    model: str | None


class PortalVehicle(PortalVehicleInfo):
    orders: list[PortalOrderSummary]


class PortalDiagnosis(_FromView):
    text: str
    updated_at: datetime


class PortalQuoteLine(_FromView):
    kind: LineKind
    description: str
    reference: str | None
    # RF-38: una pieza que no es nueva se marca de forma visible.
    part_condition: PartCondition | None
    quantity: Decimal
    unit_price_cents: int
    discount_bp: int
    vat_bp: int
    amount_cents: int


class PortalVatGroup(_FromView):
    vat_bp: int
    base_cents: int
    vat_cents: int


class PortalDecision(_FromView):
    outcome: Outcome
    channel: DecisionChannel
    decided_at: datetime


class PortalQuote(_FromView):
    id: UUID
    version_no: int
    status: QuoteStatus
    sent_at: datetime | None
    valid_until: datetime | None
    delivery_business_days: int | None
    # Aprobada la versión, la fecha prevista de entrega (RF-37).
    delivery_on: date | None
    lines: list[PortalQuoteLine]
    subtotal_cents: int
    # RF-39: el descuento global se enseña como tal, no repartido.
    global_discount_cents: int
    vat_breakdown: list[PortalVatGroup]
    total_cents: int
    decision: PortalDecision | None


class PortalWorkDone(_FromView):
    description: str
    worked_on: date


class PortalOrderDetail(_FromView):
    id: UUID
    code: str
    opened_at: datetime
    progress: PortalProgress
    vehicle: PortalVehicleInfo
    diagnosis: PortalDiagnosis | None
    # La primera es la vigente; las demás, las versiones anteriores (RF-43).
    quotes: list[PortalQuote]
    work: list[PortalWorkDone]
