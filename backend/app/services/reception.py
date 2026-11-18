"""Firmar la hoja de recepción (F6 paso 2, RF-52, arquitectura §7.3).

Firmar crea la fila de `reception_sheets` con la copia congelada de los datos de
recepción de la orden: desde ahí la hoja no cambia (invariante 6), aunque la
recepción se corrija después. Se firma de dos formas: el cliente en la pantalla
del taller, o el administrador marcando que se firmó en papel.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.domain.reception import (
    SNAPSHOT_VERSION,
    InvalidSignature,
    SignatureMethod,
    clean_signature,
)
from app.domain.work_orders import CLOSED
from app.models import AuditEntry, ReceptionSheet, Vehicle, WorkOrder
from app.repositories import reception as reception_repo
from app.repositories import vehicles as vehicle_repo
from app.repositories import work_orders as order_repo
from app.services.integrity import flush_or_conflict


@dataclass(frozen=True)
class ScreenSignature:
    """Lo que manda la pantalla de firma: el lienzo y sus trazos."""

    width: float
    height: float
    strokes: list[list[list[float]]]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def snapshot_of(order: WorkOrder, vehicle: Vehicle) -> dict[str, Any]:
    """Lo que se congela al firmar, sin datos personales: el nombre del cliente
    se lee al generar el PDF (como en el presupuesto, RF-55) y quién trajo el
    coche va en sus columnas, que se vacían al anonimizar (RF-15)."""
    return {
        "v": SNAPSHOT_VERSION,
        "order": {
            "year": order.year,
            "number": order.number,
            "type": order.type,
            "opened_at": _iso(order.created_at),
        },
        "vehicle": {
            "plate": vehicle.plate,
            "make": vehicle.make,
            "model": vehicle.model,
            "vin": vehicle.vin,
        },
        "odometer_km": order.odometer_km,
        "fuel_level": order.fuel_level,
        "visible_damage": order.visible_damage,
        "belongings": order.belongings,
        "reason": order.reason,
        "expected_delivery_at": _iso(order.expected_delivery_at),
    }


async def sign(
    session: AsyncSession,
    workshop_id: UUID,
    employee_id: UUID,
    user_id: UUID,
    order_id: UUID,
    *,
    expected_version: int,
    method: SignatureMethod,
    signer_name: str | None,
    signature: ScreenSignature | None,
) -> None:
    """Firmar la hoja de la orden, tal como estaba en `expected_version`.

    La versión es lo que hace valer la firma: quien firma ha visto esos datos, y
    si alguien los ha cambiado mientras tanto, la firma no se guarda (409). La
    orden se bloquea antes de mirar nada, como al cambiar su estado: dos firmas a
    la vez, o una firma y una corrección, van una detrás de otra.
    """
    if method == SignatureMethod.SCREEN:
        if signature is None or not signer_name:
            raise ValidationFailedError("signature_required")
        try:
            strokes = clean_signature(
                signature.width, signature.height, signature.strokes
            )
        except InvalidSignature:
            raise ValidationFailedError("signature_invalid") from None
    else:
        # En papel, la firma está en el papel; no se guarda ningún trazo.
        if signature is not None:
            raise ValidationFailedError("signature_not_expected")
        strokes = None

    order = await order_repo.get_for_update(session, order_id)
    if order is None:
        raise NotFoundError("work_order_not_found")
    if order.version != expected_version:
        raise ConflictError("modified_by_someone_else")
    # Una orden cerrada no cambia (RF-26), y la hoja es de cuando entró el coche.
    if order.status in CLOSED:
        raise ConflictError("work_order_closed")
    if await reception_repo.is_signed(session, order_id):
        raise ConflictError("reception_already_signed")
    vehicle = await vehicle_repo.get(session, order.vehicle_id)
    assert vehicle is not None, "una orden siempre tiene su vehículo"
    now = await vehicle_repo.db_now(session)

    session.add(
        ReceptionSheet(
            workshop_id=workshop_id,
            work_order_id=order_id,
            signature_method=method,
            recorded_by_employee_id=employee_id,
            snapshot=snapshot_of(order, vehicle),
            quote_waived=order.quote_waived,
            dropped_off_by_name=order.dropped_off_by_name,
            dropped_off_by_phone=order.dropped_off_by_phone,
            signer_name=signer_name or None,
            signature=strokes,
        )
    )
    # La orden cambia de versión: quien la tuviera abierta para corregir la
    # recepción recibe un 409 y ve que ya está firmada, en vez de corregir sin
    # dejar constancia (`update_order`).
    order.updated_at = now
    session.add(
        AuditEntry(
            workshop_id=workshop_id,
            actor_user_id=user_id,
            action="reception_signed",
            target_type="work_order",
            target_id=order_id,
            # Sin quién firmó: es un dato personal y la auditoría no se vacía.
            details={"signature_method": method.value},
        )
    )
    # El índice único es la última palabra si dos firmas pasan a la vez.
    await flush_or_conflict(
        session, {"uq_reception_sheets_work_order_id": "reception_already_signed"}
    )
