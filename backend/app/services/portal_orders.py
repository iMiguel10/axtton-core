"""Los vehículos y las órdenes de un cliente en el portal (F4 paso 4, RF-42, RF-43).

Lo que sale de aquí es solo lo que el cliente puede ver, campo a campo: ni notas
internas, ni quién hizo cada trabajo, ni sus horas, ni borradores, ni quién anotó
una decisión. Una orden ajena, inexistente o cancelada es el mismo 404 (T4).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.domain.portal import ClientProgress, client_progress
from app.domain.quotes import (
    DecisionChannel,
    LineKind,
    Outcome,
    PartCondition,
    QuoteStatus,
)
from app.domain.work_orders import WorkOrderStatus, order_code
from app.models import Quote, QuoteDecision, QuoteLine, Vehicle, WorkOrder
from app.repositories import portal as portal_repo
from app.repositories import quotes as quote_repo
from app.services.quotes import delivery_on, is_expired, totals_of


@dataclass(frozen=True)
class OrderSummary:
    id: UUID
    code: str
    opened_at: datetime
    progress: ClientProgress


@dataclass(frozen=True)
class VehicleInfo:
    plate: str
    make: str | None
    model: str | None


@dataclass(frozen=True)
class VehicleOrders(VehicleInfo):
    orders: list[OrderSummary]


@dataclass(frozen=True)
class Diagnosis:
    text: str
    updated_at: datetime


@dataclass(frozen=True)
class QuoteLineView:
    kind: LineKind
    description: str
    reference: str | None
    part_condition: PartCondition | None
    quantity: Decimal
    unit_price_cents: int
    discount_bp: int
    vat_bp: int
    # Sin el descuento global, que se enseña aparte (RF-39).
    amount_cents: int


@dataclass(frozen=True)
class VatGroupView:
    vat_bp: int
    base_cents: int
    vat_cents: int


@dataclass(frozen=True)
class DecisionView:
    outcome: Outcome
    channel: DecisionChannel
    decided_at: datetime


@dataclass(frozen=True)
class QuoteView:
    id: UUID
    version_no: int
    # Caducada aunque su estado aún diga "enviada" (hasta el worker, F5).
    status: QuoteStatus
    sent_at: datetime | None
    valid_until: datetime | None
    delivery_business_days: int | None
    delivery_on: date | None
    lines: list[QuoteLineView]
    subtotal_cents: int
    global_discount_cents: int
    vat_breakdown: list[VatGroupView]
    total_cents: int
    decision: DecisionView | None


@dataclass(frozen=True)
class WorkDone:
    description: str
    worked_on: date


@dataclass(frozen=True)
class OrderDetail:
    id: UUID
    code: str
    opened_at: datetime
    progress: ClientProgress
    vehicle: VehicleInfo
    diagnosis: Diagnosis | None
    # La primera es la vigente; las demás, las versiones anteriores.
    quotes: list[QuoteView]
    work: list[WorkDone]


def _progress(order: WorkOrder, now: datetime) -> ClientProgress | None:
    return client_progress(
        status=WorkOrderStatus(order.status),
        unrepaired=order.unrepaired,
        last_activity_at=order.last_activity_at,
        expected_delivery_at=order.expected_delivery_at,
        now=now,
    )


async def vehicles_of(session: AsyncSession, client_id: UUID) -> list[VehicleOrders]:
    """Sus órdenes agrupadas por vehículo. El coche con la última orden, primero."""
    now = datetime.now(UTC)
    grouped: dict[UUID, tuple[Vehicle, list[OrderSummary]]] = {}
    for order, vehicle in await portal_repo.orders_of(session, client_id):
        progress = _progress(order, now)
        if progress is None:
            continue
        _, orders = grouped.setdefault(vehicle.id, (vehicle, []))
        orders.append(
            OrderSummary(
                order.id,
                order_code(order.year, order.number),
                order.created_at,
                progress,
            )
        )
    return [
        VehicleOrders(vehicle.plate, vehicle.make, vehicle.model, orders)
        for vehicle, orders in grouped.values()
    ]


def _quote_view(
    quote: Quote,
    lines: list[QuoteLine],
    decision: QuoteDecision | None,
    timezone: str,
    now: datetime,
) -> QuoteView:
    totals = totals_of(quote, lines)
    return QuoteView(
        id=quote.id,
        version_no=quote.version_no,
        status=(
            QuoteStatus.EXPIRED if is_expired(quote, now) else QuoteStatus(quote.status)
        ),
        sent_at=quote.sent_at,
        valid_until=quote.valid_until,
        delivery_business_days=quote.delivery_business_days,
        delivery_on=delivery_on(quote, decision, timezone),
        lines=[
            QuoteLineView(
                kind=LineKind(line.kind),
                description=line.description,
                reference=line.reference,
                part_condition=(
                    PartCondition(line.part_condition) if line.part_condition else None
                ),
                quantity=line.quantity,
                unit_price_cents=line.unit_price_cents,
                discount_bp=line.discount_bp,
                vat_bp=line.vat_bp,
                amount_cents=amounts.gross_cents - amounts.discount_cents,
            )
            for line, amounts in zip(lines, totals.lines, strict=True)
        ],
        subtotal_cents=totals.subtotal_cents,
        global_discount_cents=totals.global_discount_cents,
        vat_breakdown=[
            VatGroupView(group.vat_bp, group.base_cents, group.vat_cents)
            for group in totals.vat_breakdown
        ],
        total_cents=totals.total_cents,
        decision=(
            DecisionView(
                Outcome(decision.outcome),
                DecisionChannel(decision.channel),
                decision.decided_at,
            )
            if decision
            else None
        ),
    )


async def order_detail(
    session: AsyncSession, client_id: UUID, order_id: UUID, *, timezone: str
) -> OrderDetail:
    now = datetime.now(UTC)
    found = await portal_repo.order_of(session, client_id, order_id)
    progress = None if found is None else _progress(found[0], now)
    if found is None or progress is None:
        raise NotFoundError("work_order_not_found")
    order, vehicle = found

    diagnosis = await portal_repo.current_diagnosis(session, order.id)
    quotes = await portal_repo.sent_quotes(session, order.id)
    ids = [quote.id for quote in quotes]
    lines = await quote_repo.lines_of(session, ids)
    decisions = await quote_repo.decisions_of(session, ids)

    def decision_of(quote: Quote) -> QuoteDecision | None:
        found_decision = decisions.get(quote.id)
        return found_decision[0] if found_decision else None

    return OrderDetail(
        id=order.id,
        code=order_code(order.year, order.number),
        opened_at=order.created_at,
        progress=progress,
        vehicle=VehicleInfo(vehicle.plate, vehicle.make, vehicle.model),
        diagnosis=(
            Diagnosis(diagnosis.text, diagnosis.created_at) if diagnosis else None
        ),
        quotes=[
            _quote_view(
                quote, lines.get(quote.id, []), decision_of(quote), timezone, now
            )
            for quote in quotes
        ],
        work=[
            WorkDone(entry.description, entry.worked_on)
            for entry in await portal_repo.work_done(session, order.id)
        ],
    )
