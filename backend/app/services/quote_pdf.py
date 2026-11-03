"""El PDF de una versión de presupuesto (F3 paso 7, RF-37, RF-55, A14).

Se genera al pedirlo y no se guarda. De una versión enviada, con lo que se
congeló al enviarla: sus líneas e importes, su validez, su plazo de entrega y el
vehículo con sus km. Por eso sale idéntico cada vez para el mismo estado; cambia
solo cuando el cliente decide (RF-55), porque entonces lleva la fecha y el canal
de la decisión. Los datos del taller, su logotipo y el nombre del cliente se
leen al generarlo: el taller puede corregir su domicilio, y el nombre tiene que
desaparecer si se anonimiza al cliente (RF-15).

De un borrador, la vista previa: lo mismo calculado en el momento y con la marca
de agua "Borrador, no válido".

El documento va en español, el idioma de la normativa que lo exige (RD
1457/1986).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError
from app.domain.money import format_eur, format_quantity, format_vat
from app.domain.quotes import DecisionChannel, LineKind, PartCondition, QuoteStatus
from app.domain.work_orders import order_code
from app.infra.pdf import Resource, render_pdf
from app.models import Quote, Workshop
from app.repositories import quotes as quote_repo
from app.repositories import settings as settings_repo
from app.repositories import work_orders as order_repo
from app.services.quotes import (
    delivery_on,
    is_expired,
    totals_of,
    vehicle_snapshot,
)
from app.services.settings import prices_hidden

KIND = {
    LineKind.LABOR: "Mano de obra",
    LineKind.PART: "Pieza",
    LineKind.OTHER: "Otros",
}
# RF-38: una pieza que no es nueva se marca de forma visible.
CONDITION = {
    PartCondition.USED: "Usada",
    PartCondition.RECONDITIONED: "Reacondicionada",
    PartCondition.NON_SPECIFIC: "No específica del modelo",
}
CHANNEL = {
    DecisionChannel.PORTAL: "en el portal del cliente",
    DecisionChannel.PHONE: "por teléfono",
    DecisionChannel.IN_PERSON: "en persona, en el taller",
}


@dataclass(frozen=True)
class QuotePdf:
    filename: str
    content: bytes


def _day(moment: datetime, zone: ZoneInfo) -> str:
    return moment.astimezone(zone).strftime("%d/%m/%Y")


def _status(quote: Quote, expired: bool) -> str:
    if quote.status == QuoteStatus.DRAFT:
        return "Borrador, no válido"
    if expired:
        return "Caducado: ya no se puede aceptar"
    return {
        QuoteStatus.SENT: "Pendiente de la decisión del cliente",
        QuoteStatus.APPROVED: "Aceptado",
        QuoteStatus.REJECTED: "Rechazado",
        QuoteStatus.SUPERSEDED: "Sustituido por una versión posterior",
        QuoteStatus.CANCELLED: "Anulado por el taller",
    }[QuoteStatus(quote.status)]


def _missing_legal_data(workshop: Workshop) -> list[str]:
    """Lo que RF-37 exige del taller y aún no ha rellenado su administrador."""
    required = {
        "la razón social o el nombre": workshop.legal_name or workshop.name,
        "el NIF": workshop.tax_id,
        "el domicilio": workshop.address,
        "el número de registro industrial": workshop.industrial_registry_number,
    }
    return [label for label, value in required.items() if not value]


async def quote_pdf(
    session: AsyncSession, workshop_id: UUID, role: str, quote_id: UUID
) -> QuotePdf:
    quote = await quote_repo.get(session, quote_id)
    if quote is None:
        raise NotFoundError("quote_not_found")
    # Un presupuesto sin importes no es un presupuesto: quien no puede verlos
    # (el mecánico, si el taller lo desactiva) tampoco descarga el PDF.
    if await prices_hidden(session, workshop_id, role):
        raise ForbiddenError("quote_prices_hidden")
    row = await order_repo.get_row(session, quote.work_order_id)
    assert row is not None  # FK: la versión no existe sin su orden
    workshop = await settings_repo.get_workshop(session, workshop_id)
    assert workshop is not None
    logo = await settings_repo.get_logo(session, workshop_id)
    lines = (await quote_repo.lines_of(session, [quote.id])).get(quote.id, [])
    decisions = await quote_repo.decisions_of(session, [quote.id])

    zone = ZoneInfo(workshop.timezone)
    draft = quote.status == QuoteStatus.DRAFT
    totals = totals_of(quote, lines)
    expired = is_expired(quote, datetime.now(zone))
    found = decisions.get(quote.id)
    decision, recorded_by = found if found else (None, None)
    vehicle = (
        vehicle_snapshot(row.vehicle, row.order)
        if quote.vehicle_snapshot is None
        else quote.vehicle_snapshot
    )
    code = order_code(row.order.year, row.order.number)
    delivery = delivery_on(quote, decision, workshop.timezone)

    context: dict[str, Any] = {
        "draft": draft,
        "status": _status(quote, expired),
        "number": f"{code} · versión {quote.version_no}",
        "workshop": {
            "name": workshop.name,
            "legal_name": workshop.legal_name,
            "tax_id": workshop.tax_id,
            "address": workshop.address,
            "phone": workshop.phone,
            "email": workshop.reply_to_email,
            "registry": workshop.industrial_registry_number,
        },
        "has_logo": logo is not None,
        "missing": _missing_legal_data(workshop) if draft else [],
        # Anonimizado (RF-15), el nombre está vacío.
        "client": row.client.name or "Cliente eliminado",
        "vehicle": {
            "plate": vehicle["plate"],
            "make_model": " ".join(
                part for part in (vehicle["make"], vehicle["model"]) if part
            ),
            "odometer_km": (
                f"{vehicle['odometer_km']:,} km".replace(",", ".")
                if vehicle["odometer_km"] is not None
                else None
            ),
        },
        "date": _day(quote.sent_at, zone) if quote.sent_at else None,
        # `valid_until` es la medianoche que cierra el último día hábil.
        "valid_until": (
            _day(quote.valid_until - timedelta(seconds=1), zone)
            if quote.valid_until
            else None
        ),
        "validity_days": workshop.quote_validity_business_days,
        "delivery_days": quote.delivery_business_days,
        "delivery_on": delivery.strftime("%d/%m/%Y") if delivery else None,
        "lines": [
            {
                "kind": KIND[LineKind(line.kind)],
                "description": line.description,
                "reference": line.reference,
                "condition": (
                    CONDITION.get(PartCondition(line.part_condition))
                    if line.part_condition
                    else None
                ),
                "quantity": format_quantity(line.quantity),
                "unit_price": format_eur(line.unit_price_cents),
                "discount": format_vat(line.discount_bp) if line.discount_bp else "",
                "vat": format_vat(line.vat_bp),
                # Sin el descuento global, que se enseña aparte (RF-39).
                "amount": format_eur(amounts.gross_cents - amounts.discount_cents),
            }
            for line, amounts in zip(lines, totals.lines, strict=True)
        ],
        "has_conditions": any(
            line.part_condition not in (None, PartCondition.NEW) for line in lines
        ),
        "subtotal": format_eur(totals.subtotal_cents),
        # RF-39: el descuento global se enseña como tal, no repartido.
        "global_discount": (
            format_eur(totals.global_discount_cents)
            if totals.global_discount_cents
            else None
        ),
        "global_discount_percent": (
            format_vat(quote.global_discount_value or 0)
            if quote.global_discount_kind == "percent"
            else None
        ),
        "vat_breakdown": [
            {
                "rate": format_vat(group.vat_bp),
                "base": format_eur(group.base_cents),
                "vat": format_eur(group.vat_cents),
            }
            for group in totals.vat_breakdown
        ],
        "total": format_eur(totals.total_cents),
        "decision": (
            {
                "approved": decision.outcome == "approved",
                "when": decision.decided_at.astimezone(zone).strftime(
                    "%d/%m/%Y a las %H:%M"
                ),
                "channel": CHANNEL[DecisionChannel(decision.channel)],
                "recorded_by": recorded_by,
            }
            if decision
            else None
        ),
        "cancel_reason": quote.cancel_reason,
    }
    resources = (
        {"logo": Resource(logo.content, logo.media_type)} if logo is not None else {}
    )
    content = await render_pdf("quote.html", context, resources)
    prefix = "borrador" if draft else "presupuesto"
    return QuotePdf(f"{prefix}-{code}-v{quote.version_no}.pdf", content)
