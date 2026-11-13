"""Lo común a los avisos de una orden (F5 pasos 5 y 6): a quién, de qué taller y
adónde lleva el botón, o por qué no hay que enviar nada.

Lo usan los compositores con el aviso ya bloqueado: entre el cambio que lo creó y
el envío pudo pasar cualquier cosa, así que todo se vuelve a leer aquí.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.clients import Language
from app.domain.emails import NoticeContext
from app.domain.notifications import FailureReason, NotificationStatus
from app.domain.portal import order_link
from app.domain.work_orders import order_code
from app.models import Client, Notification, WorkOrder, Workshop
from app.repositories import clients as client_repo
from app.repositories import settings as settings_repo
from app.repositories import work_orders as order_repo
from app.services.notifications import NotDelivered

OBSOLETE = NotDelivered(NotificationStatus.CANCELLED, FailureReason.OBSOLETE)


@dataclass(frozen=True)
class Recipient:
    order: WorkOrder
    client: Client
    workshop: Workshop
    # El email del cliente, que existe: sin él, `load` ya dijo `skipped`.
    email: str


async def load(
    session: AsyncSession, notification: Notification
) -> Recipient | NotDelivered:
    """La orden, el cliente y el taller del aviso, o por qué no se envía:
    `cancelled` con el cliente anonimizado o archivado, el taller desactivado o
    la orden de otro cliente; `skipped` si el cliente no tiene email (RF-63)."""
    assert notification.work_order_id is not None
    order = await order_repo.get(session, notification.work_order_id)
    client = await client_repo.get(session, notification.client_id)
    workshop = await settings_repo.get_workshop(session, notification.workshop_id)
    if order is None or client is None or workshop is None:
        return OBSOLETE
    if (
        workshop.status != "active"
        or client.anonymized_at is not None
        or client.archived_at is not None
        # El cliente de la orden es el destinatario; si no, algo cambió.
        or order.client_id != client.id
    ):
        return OBSOLETE
    if not client.email:
        return NotDelivered(NotificationStatus.SKIPPED, FailureReason.NO_EMAIL)
    return Recipient(order, client, workshop, client.email)


def vehicle_label(vehicle: dict[str, Any] | None) -> str:
    """ "1234 BCD · Peugeot 308", de lo que haya."""
    data = vehicle or {}
    model = " ".join(part for part in (data.get("make"), data.get("model")) if part)
    return " · ".join(part for part in (data.get("plate"), model) if part)


def notice_for(recipient: Recipient, vehicle: str) -> NoticeContext:
    order, workshop = recipient.order, recipient.workshop
    return NoticeContext(
        language=Language(recipient.client.language),
        workshop_name=workshop.name,
        reply_to=workshop.reply_to_email,
        order_code=order_code(order.year, order.number),
        vehicle=vehicle,
        link=order_link(
            get_settings().app_url, workshop.id, workshop.portal_slug, order.id
        ),
    )
