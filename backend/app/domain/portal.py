"""Reglas puras del portal del cliente (F4). Sin I/O."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from app.domain.work_orders import CLOSED, WorkOrderStatus

# Validez de un enlace mágico (especificación §10): el cliente puede abrir el
# correo un rato después, pero un enlace olvidado en un buzón no debe valer.
LINK_LIFETIME = timedelta(minutes=15)

# Cuánto dura una sesión del portal (RF-47), desde que se entra. SuperTokens solo
# tiene una duración, la misma para el personal, así que esta se comprueba aquí.
SESSION_LIFETIME = timedelta(days=30)


@dataclass(frozen=True)
class PortalLogin:
    """Quién entra en el portal, decidido por el servidor al consumir un enlace.

    Es lo único que `core/sessions.py` acepta para crear una sesión de cliente:
    el taller y el cliente salen del enlace guardado, nunca de la petición.
    """

    workshop_id: UUID
    client_id: UUID
    email: str
    # La cerradura del cliente al consumir el enlace: si sube después, esta sesión
    # no vale, aunque se cree más tarde.
    portal_epoch: int


def access_link(app_url: str, workshop_id: UUID, token: str) -> str:
    """La dirección del enlace que recibe el cliente.

    El token va en el fragmento (`#`), que el navegador nunca envía al servidor:
    no queda en los registros del proxy ni en la cabecera Referer. El taller va en
    la ruta: es el que la API fija para RLS al consumirlo (T5).
    """
    return f"{app_url.rstrip('/')}/portal/access/{workshop_id}#{token}"


class ClientOrderStatus(StrEnum):
    """Lo que ve el cliente de una orden (especificación §6).

    La API del portal solo envía estos valores, nunca los estados internos.
    """

    IN_REVIEW = "in_review"
    AWAITING_RESPONSE = "awaiting_response"
    IN_REPAIR = "in_repair"
    WAITING_PARTS = "waiting_parts"
    READY = "ready"
    READY_UNREPAIRED = "ready_unrepaired"
    DELIVERED = "delivered"


# `None`: no aparece en el portal (una cancelada se abrió por error).
_CLIENT_STATUS: dict[WorkOrderStatus, ClientOrderStatus | None] = {
    WorkOrderStatus.RECEIVED: ClientOrderStatus.IN_REVIEW,
    WorkOrderStatus.DIAGNOSING: ClientOrderStatus.IN_REVIEW,
    WorkOrderStatus.PENDING_APPROVAL: ClientOrderStatus.AWAITING_RESPONSE,
    WorkOrderStatus.APPROVED: ClientOrderStatus.IN_REPAIR,
    WorkOrderStatus.IN_REPAIR: ClientOrderStatus.IN_REPAIR,
    WorkOrderStatus.WAITING_PARTS: ClientOrderStatus.WAITING_PARTS,
    WorkOrderStatus.READY: ClientOrderStatus.READY,
    WorkOrderStatus.DELIVERED: ClientOrderStatus.DELIVERED,
    WorkOrderStatus.CANCELLED: None,
}

# Con el coche listo, la fecha prevista ya no promete nada.
_DELIVERY_SETTLED = CLOSED | {WorkOrderStatus.READY}


@dataclass(frozen=True)
class ClientProgress:
    """En qué va una orden, dicho para el cliente (§6, RF-42, RF-80)."""

    status: ClientOrderStatus
    updated_at: datetime
    # `None` si no la hay o si ya no importa: el coche está listo o entregado.
    expected_delivery_at: datetime | None
    # La fecha pasó y el coche no está listo: el portal lo dice en vez de
    # seguir enseñándola como si valiera (RF-80).
    delivery_overdue: bool


def client_progress(
    *,
    status: WorkOrderStatus,
    unrepaired: bool,
    last_activity_at: datetime,
    expected_delivery_at: datetime | None,
    now: datetime,
) -> ClientProgress | None:
    """Traduce una orden a lo que ve su cliente; `None` si no debe verla.

    La última actualización es `last_activity_at`: cambios de estado y trabajos
    registrados, lo que el cliente puede ver. Una nota interna no la mueve. "Pasada"
    es lo mismo que en el filtro de órdenes del taller (RF-24): el instante ya pasó.
    """
    client_status = _CLIENT_STATUS[status]
    if client_status is None:
        return None
    if client_status is ClientOrderStatus.READY and unrepaired:
        client_status = ClientOrderStatus.READY_UNREPAIRED
    expected = None if status in _DELIVERY_SETTLED else expected_delivery_at
    return ClientProgress(
        status=client_status,
        updated_at=last_activity_at,
        expected_delivery_at=expected,
        delivery_overdue=expected is not None and expected < now,
    )
