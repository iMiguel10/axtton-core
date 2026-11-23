"""El resumen de entrega (F6 paso 4, RF-53, RF-55).

Se genera al pedirlo y no se guarda. Sale de la orden entregada, que ya no
cambia (RF-26): sus trabajos sin anular, la última versión aprobada del
presupuesto (congelada al enviarla), los km de entrada y de salida, la fecha de
entrega y la garantía. Por eso sale idéntico cada vez (RF-55). Los datos del
taller, su logotipo, el vehículo y el nombre del cliente se leen al generarlo,
como en los demás documentos: el nombre desaparece al anonimizar (RF-15).

Las piezas montadas, hasta que exista el inventario (F7), son las líneas de pieza
del presupuesto aprobado (decidido por el usuario al planificar F6).

Lleva escrito "Este documento no es una factura": se le parece mucho (RF-53).
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.domain.delivery import WARRANTY_KM, WARRANTY_MONTHS, warranty_of
from app.domain.money import format_eur, format_quantity
from app.domain.quotes import LineKind, PartCondition
from app.domain.work_orders import (
    NoQuoteReason,
    WorkOrderStatus,
    WorkOrderType,
    order_code,
)
from app.infra.pdf import Resource, render_pdf
from app.repositories import quotes as quote_repo
from app.repositories import settings as settings_repo
from app.repositories import work_orders as order_repo
from app.repositories import worklog as worklog_repo
from app.services.quote_pdf import CONDITION
from app.services.reception_pdf import TYPE
from app.services.settings import prices_hidden

NO_QUOTE = {
    NoQuoteReason.WAIVER: "el cliente renunció al presupuesto",
    NoQuoteReason.WARRANTY: "trabajo en garantía",
    NoQuoteReason.FIXED_PRICE: "trabajo a precio cerrado",
}


@dataclass(frozen=True)
class DeliveryPdf:
    filename: str
    content: bytes


def _km(value: int | None) -> str | None:
    return f"{value:,} km".replace(",", ".") if value is not None else None


async def delivery_summary_pdf(
    session: AsyncSession, workshop_id: UUID, role: str, order_id: UUID
) -> DeliveryPdf:
    """El resumen de una orden entregada. Lleva el importe del presupuesto
    aprobado: quien no ve importes (el mecánico, si el taller lo desactiva) no
    lo descarga, como el PDF del presupuesto."""
    row = await order_repo.get_row(session, order_id)
    if row is None:
        raise NotFoundError("work_order_not_found")
    if row.order.status != WorkOrderStatus.DELIVERED:
        raise ConflictError("work_order_not_delivered")
    if await prices_hidden(session, workshop_id, role):
        raise ForbiddenError("quote_prices_hidden")
    return await _render(session, workshop_id, row)


async def _render(
    session: AsyncSession, workshop_id: UUID, row: order_repo.OrderRow
) -> DeliveryPdf:
    order = row.order
    workshop = await settings_repo.get_workshop(session, workshop_id)
    assert workshop is not None
    logo = await settings_repo.get_logo(session, workshop_id)
    zone = ZoneInfo(workshop.timezone)
    assert order.delivered_at is not None, "una orden entregada tiene su fecha"
    delivered = order.delivered_at.astimezone(zone)
    entries = [
        entry
        for entry, _worker, _recorder in await worklog_repo.work_entries(
            session, order.id
        )
        if entry.voided_at is None
    ]
    quote = await quote_repo.last_approved(session, order.id)
    lines = (
        (await quote_repo.lines_of(session, [quote.id])).get(quote.id, [])
        if quote
        else []
    )
    warranty = warranty_of(
        delivered.date(), order.delivered_odometer_km, unrepaired=order.unrepaired
    )
    code = order_code(order.year, order.number)

    context: dict[str, Any] = {
        "number": code,
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
        "type": TYPE[WorkOrderType(order.type)],
        "client": row.client.name or "Cliente eliminado",
        "vehicle": {
            "plate": row.vehicle.plate,
            "make_model": " ".join(
                part for part in (row.vehicle.make, row.vehicle.model) if part
            ),
            "vin": row.vehicle.vin,
        },
        "received_on": order.created_at.astimezone(zone).strftime("%d/%m/%Y"),
        "delivered_on": delivered.strftime("%d/%m/%Y"),
        "odometer_in": _km(order.odometer_km),
        "odometer_out": _km(order.delivered_odometer_km),
        "unrepaired": order.unrepaired,
        "works": [
            {"day": entry.worked_on.strftime("%d/%m/%Y"), "text": entry.description}
            for entry in entries
        ],
        "parts": [
            {
                "description": line.description,
                "reference": line.reference,
                "quantity": format_quantity(line.quantity),
                "condition": (
                    CONDITION.get(PartCondition(line.part_condition))
                    if line.part_condition
                    else None
                ),
            }
            for line in lines
            if line.kind == LineKind.PART
        ],
        "quote": (
            {
                "version": quote.version_no,
                "total": format_eur(quote.total_cents or 0),
            }
            if quote
            else None
        ),
        "no_quote_reason": (
            NO_QUOTE[NoQuoteReason(order.no_quote_reason)]
            if order.no_quote_reason
            else None
        ),
        "warranty": (
            {
                "until": warranty.until.strftime("%d/%m/%Y"),
                "until_km": _km(warranty.until_km),
                "months": WARRANTY_MONTHS,
                "km": _km(WARRANTY_KM),
            }
            if warranty
            else None
        ),
    }
    resources = (
        {"logo": Resource(logo.content, logo.media_type)} if logo is not None else {}
    )
    content = await render_pdf("delivery.html", context, resources)
    return DeliveryPdf(f"resumen-de-entrega-{code}.pdf", content)
