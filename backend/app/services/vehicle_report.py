"""El informe de actuaciones de un vehículo (F6 paso 5, RF-18, RNF-52).

Todas las órdenes del vehículo, de cualquier titular, sin las canceladas: la
fecha, los km, el diagnóstico para el cliente, los trabajos sin anular y las
piezas montadas. Las piezas, hasta que exista el inventario (F7), son las líneas
de pieza del último presupuesto aprobado, como en el resumen de entrega.

El informe suele acabar en manos de quien compra el coche, así que por defecto
no lleva ni los titulares ni los importes. El administrador puede pedirlos
(`owners`, `amounts`), y eso queda en la auditoría (RNF-16): con los titulares
lleva datos personales de clientes que ya no son del coche.

Se genera al pedirlo y no se guarda (A14). No es un documento con valor de
prueba (RF-55): cambia con cada orden nueva, y lleva la fecha en que se generó.
"""

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError
from app.domain.money import format_eur, format_quantity
from app.domain.permissions import Action, can
from app.domain.quotes import LineKind, PartCondition
from app.domain.work_orders import WorkOrderStatus, WorkOrderType, order_code
from app.infra.pdf import Resource, render_pdf
from app.models import AuditEntry
from app.repositories import quotes as quote_repo
from app.repositories import settings as settings_repo
from app.repositories import vehicle_report as report_repo
from app.repositories import vehicles as vehicle_repo
from app.services.quote_pdf import CONDITION
from app.services.reception_pdf import TYPE


@dataclass(frozen=True)
class ReportPdf:
    filename: str
    content: bytes


def _km(value: int | None) -> str | None:
    return f"{value:,} km".replace(",", ".") if value is not None else None


async def vehicle_report_pdf(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    role: str,
    vehicle_id: UUID,
    *,
    owners: bool = False,
    amounts: bool = False,
) -> ReportPdf:
    if (owners or amounts) and not can(role, Action.EXTEND_VEHICLE_REPORT):
        raise ForbiddenError("vehicle_report_extended_forbidden")
    vehicle = await vehicle_repo.get(session, vehicle_id)
    if vehicle is None:
        raise NotFoundError("vehicle_not_found")
    workshop = await settings_repo.get_workshop(session, workshop_id)
    assert workshop is not None
    logo = await settings_repo.get_logo(session, workshop_id)
    zone = ZoneInfo(workshop.timezone)

    rows = await report_repo.orders_of(session, vehicle_id)
    ids = [order.id for order, _name in rows]
    diagnoses = await report_repo.current_diagnoses(session, ids)
    works = await report_repo.work_entries_of(session, ids)
    approved = await report_repo.last_approved_of(session, ids)
    lines = await quote_repo.lines_of(session, [q.id for q in approved.values()])
    now = await vehicle_repo.db_now(session)

    if owners or amounts:
        session.add(
            AuditEntry(
                workshop_id=workshop_id,
                actor_user_id=user_id,
                action="vehicle_report_extended",
                target_type="vehicle",
                target_id=vehicle_id,
                details={"owners": owners, "amounts": amounts},
            )
        )

    orders: list[dict[str, Any]] = []
    for order, client_name in rows:
        quote = approved.get(order.id)
        delivered = (
            order.delivered_at.astimezone(zone).strftime("%d/%m/%Y")
            if order.status == WorkOrderStatus.DELIVERED and order.delivered_at
            else None
        )
        orders.append(
            {
                "code": order_code(order.year, order.number),
                "type": TYPE[WorkOrderType(order.type)],
                "received_on": order.created_at.astimezone(zone).strftime("%d/%m/%Y"),
                "delivered_on": delivered,
                "unrepaired": order.unrepaired,
                "odometer_in": _km(order.odometer_km),
                "odometer_out": _km(order.delivered_odometer_km),
                "client": (client_name or "Cliente eliminado") if owners else None,
                "diagnosis": diagnoses.get(order.id),
                "works": [
                    {
                        "day": entry.worked_on.strftime("%d/%m/%Y"),
                        "text": entry.description,
                    }
                    for entry in works.get(order.id, [])
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
                    for line in (lines.get(quote.id, []) if quote else [])
                    if line.kind == LineKind.PART
                ],
                "amount": (
                    format_eur(quote.total_cents or 0) if amounts and quote else None
                ),
            }
        )

    context: dict[str, Any] = {
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
        "vehicle": {
            "plate": vehicle.plate,
            "make_model": " ".join(
                part for part in (vehicle.make, vehicle.model) if part
            ),
            "vin": vehicle.vin,
        },
        "generated_on": now.astimezone(zone).strftime("%d/%m/%Y"),
        "owners": owners,
        "amounts": amounts,
        "orders": orders,
    }
    resources = (
        {"logo": Resource(logo.content, logo.media_type)} if logo is not None else {}
    )
    content = await render_pdf("vehicle_report.html", context, resources)
    plate = re.sub(r"[^A-Za-z0-9]", "", vehicle.plate) or "vehiculo"
    return ReportPdf(f"informe-de-actuaciones-{plate}.pdf", content)
