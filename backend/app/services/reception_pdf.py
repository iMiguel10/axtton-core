"""El PDF de la hoja de recepción (F6 paso 3, RF-51, RF-52, RF-55).

Se genera al pedirlo y no se guarda, como el del presupuesto. Sin firmar, con los
datos de recepción de la orden tal como están, para imprimirla y firmarla en
papel. Firmada, siempre desde la copia congelada al firmar (`snapshot` y las
columnas de quién trajo el coche y quién firmó): corregir después la recepción
no la cambia, y sale idéntica byte a byte cada vez (RF-55).

Las dos salen por el mismo camino: la sin firmar se construye con la misma
función que congela la firmada (`snapshot_of`), así que lo que se ve antes de
firmar es exactamente lo que queda firmado.

Los datos del taller, su logotipo y el nombre del cliente se leen al generarla,
como en el presupuesto: el taller puede corregir su domicilio, y el nombre
desaparece al anonimizar (RF-15). El documento va en español, como el
presupuesto.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.domain.reception import FuelLevel, SignatureMethod, signature_svg
from app.domain.work_orders import WorkOrderStatus, WorkOrderType, order_code
from app.infra.pdf import Resource, render_pdf
from app.repositories import portal as portal_repo
from app.repositories import reception as reception_repo
from app.repositories import settings as settings_repo
from app.repositories import work_orders as order_repo
from app.services.reception import snapshot_of

TYPE = {
    WorkOrderType.BREAKDOWN: "Avería",
    WorkOrderType.MAINTENANCE: "Mantenimiento",
    WorkOrderType.ITV: "ITV",
    WorkOrderType.WARRANTY: "Garantía",
    WorkOrderType.BODYWORK: "Chapa y pintura",
    WorkOrderType.OTHER: "Otro",
}
FUEL = {
    FuelLevel.RESERVE: "En reserva",
    FuelLevel.QUARTER: "1/4",
    FuelLevel.HALF: "1/2",
    FuelLevel.THREE_QUARTERS: "3/4",
    FuelLevel.FULL: "Lleno",
}


@dataclass(frozen=True)
class ReceptionPdf:
    filename: str
    content: bytes


def _when(value: str | datetime | None, zone: ZoneInfo, pattern: str) -> str | None:
    if value is None:
        return None
    moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    return moment.astimezone(zone).strftime(pattern)


async def client_reception_pdf(
    session: AsyncSession, workshop_id: UUID, client_id: UUID, order_id: UUID
) -> ReceptionPdf:
    """La del cliente en el portal (F6 paso 6, RF-54): solo de una orden suya y
    solo firmada (decidido por el usuario). La sin firmar es para imprimirla en el
    mostrador y cambia mientras se corrige la recepción. Una orden ajena,
    inexistente o cancelada es el mismo 404 que en el resto del portal (T4)."""
    found = await portal_repo.order_of(session, client_id, order_id)
    if found is None or found[0].status == WorkOrderStatus.CANCELLED:
        raise NotFoundError("work_order_not_found")
    if not await reception_repo.is_signed(session, order_id):
        raise NotFoundError("reception_sheet_not_found")
    return await reception_pdf(session, workshop_id, order_id, for_client=True)


async def reception_pdf(
    session: AsyncSession, workshop_id: UUID, order_id: UUID, *, for_client: bool
) -> ReceptionPdf:
    """La hoja de la orden: firmada, desde su copia; si no, desde la orden.

    `for_client` (el portal, paso 6) quita el nombre del empleado que recogió la
    firma o la marcó, como en el PDF del presupuesto (RF-43)."""
    row = await order_repo.get_row(session, order_id)
    if row is None:
        raise NotFoundError("work_order_not_found")
    workshop = await settings_repo.get_workshop(session, workshop_id)
    assert workshop is not None
    logo = await settings_repo.get_logo(session, workshop_id)
    signed = await reception_repo.of_order(session, order_id)
    zone = ZoneInfo(workshop.timezone)

    if signed is None:
        data = snapshot_of(row.order, row.vehicle)
        dropped_off = (row.order.dropped_off_by_name, row.order.dropped_off_by_phone)
        waived = row.order.quote_waived
    else:
        sheet = signed.sheet
        data = sheet.snapshot
        dropped_off = (sheet.dropped_off_by_name, sheet.dropped_off_by_phone)
        waived = sheet.quote_waived

    code = order_code(data["order"]["year"], data["order"]["number"])
    vehicle = data["vehicle"]
    signature: dict[str, Any] | None = None
    resources: dict[str, Resource] = {}
    if logo is not None:
        resources["logo"] = Resource(logo.content, logo.media_type)
    if signed is not None:
        sheet = signed.sheet
        if sheet.signature is not None:
            resources["signature"] = Resource(
                signature_svg(sheet.signature).encode(), "image/svg+xml"
            )
        signature = {
            "screen": sheet.signature_method == SignatureMethod.SCREEN,
            "when": _when(sheet.signed_at, zone, "%d/%m/%Y a las %H:%M"),
            "day": _when(sheet.signed_at, zone, "%d/%m/%Y"),
            "signer": sheet.signer_name,
            "has_image": sheet.signature is not None,
            # Ya borrada al vencer su plazo: queda "firmada el día X" (RF-56).
            "purged": sheet.signature_purged_at is not None,
            "recorded_by": None if for_client else signed.recorded_by_name,
        }

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
        "type": TYPE.get(WorkOrderType(data["order"]["type"])),
        "received_at": _when(data["order"]["opened_at"], zone, "%d/%m/%Y %H:%M"),
        # Anonimizado (RF-15), el nombre está vacío.
        "client": row.client.name or "Cliente eliminado",
        "dropped_off_by": " · ".join(part for part in dropped_off if part) or None,
        "vehicle": {
            "plate": vehicle["plate"],
            "make_model": " ".join(
                part for part in (vehicle["make"], vehicle["model"]) if part
            ),
            "vin": vehicle["vin"],
        },
        "odometer_km": (
            f"{data['odometer_km']:,} km".replace(",", ".")
            if data["odometer_km"] is not None
            else None
        ),
        "fuel_level": FUEL[FuelLevel(data["fuel_level"])]
        if data["fuel_level"]
        else None,
        "visible_damage": data["visible_damage"],
        "belongings": data["belongings"],
        "reason": data["reason"],
        "expected_delivery": _when(
            data["expected_delivery_at"], zone, "%d/%m/%Y %H:%M"
        ),
        "waived": waived,
        "signature": signature,
    }
    content = await render_pdf("reception.html", context, resources)
    return ReceptionPdf(f"hoja-de-recepcion-{code}.pdf", content)
