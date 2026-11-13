"""Los avisos de presupuesto al cliente (F5 paso 5, RF-60): enviado y anulado.

Cada aviso nace en la transacción del cambio (`notice_sent`, `notice_cancelled`,
invariante 8) y lo escribe, al enviarlo, su compositor, que vuelve a comprobar
que el motivo sigue vigente (arquitectura §8, "doble comprobación al enviar"):

- **Presupuesto enviado**: solo si la versión sigue esperando respuesta y en
  plazo. Si el taller la corrigió antes de que saliera el aviso, sale solo el de
  la versión nueva.
- **Presupuesto anulado**: solo si el cliente recibió (o pudo recibir) el aviso
  de esa versión. Si no, no tiene sentido avisarle de que se retiró algo que
  nunca le llegó (especificación §6: "avisa al cliente si ya lo había recibido").

Los dos se cancelan si el cliente está anonimizado o archivado o el taller
desactivado, y se omiten si el cliente no tiene email (RF-63).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.business_days import last_valid_day
from app.domain.clients import Language
from app.domain.emails import (
    NoticeContext,
    quote_cancelled_email,
    quote_sent_email,
)
from app.domain.notifications import (
    FailureReason,
    NotificationKind,
    NotificationStatus,
)
from app.domain.portal import order_link
from app.domain.quotes import QuoteStatus
from app.domain.work_orders import order_code
from app.infra.email import Email, compose
from app.models import Client, Notification, Quote, WorkOrder
from app.repositories import clients as client_repo
from app.repositories import notifications as notification_repo
from app.repositories import quotes as quote_repo
from app.repositories import settings as settings_repo
from app.repositories import work_orders as order_repo
from app.services import notifications as notification_service
from app.services.notifications import NotDelivered

OBSOLETE = NotDelivered(NotificationStatus.CANCELLED, FailureReason.OBSOLETE)


def sent_key(quote: Quote) -> str:
    return f"quote_sent:{quote.id}"


def cancelled_key(quote: Quote) -> str:
    return f"quote_cancelled:{quote.id}"


async def notice_sent(session: AsyncSession, order: WorkOrder, quote: Quote) -> None:
    """El aviso de una versión enviada (al enviar, corregir o renovar), en la
    transacción del envío."""
    await notification_service.create(
        session,
        workshop_id=order.workshop_id,
        kind=NotificationKind.QUOTE_SENT,
        dedupe_key=sent_key(quote),
        client_id=order.client_id,
        work_order_id=order.id,
        quote_id=quote.id,
    )


async def notice_cancelled(
    session: AsyncSession, order: WorkOrder, quote: Quote
) -> None:
    """El aviso de una versión anulada, en la transacción de la anulación."""
    await notification_service.create(
        session,
        workshop_id=order.workshop_id,
        kind=NotificationKind.QUOTE_CANCELLED,
        dedupe_key=cancelled_key(quote),
        client_id=order.client_id,
        work_order_id=order.id,
        quote_id=quote.id,
    )


async def _context(
    session: AsyncSession, notification: Notification
) -> tuple[Quote, NoticeContext, Client, str] | NotDelivered:
    """Lo común a los dos avisos, o por qué no hay que enviar nada."""
    assert notification.quote_id is not None and notification.work_order_id is not None
    quote = await quote_repo.get(session, notification.quote_id)
    order = await order_repo.get(session, notification.work_order_id)
    client = await client_repo.get(session, notification.client_id)
    workshop = await settings_repo.get_workshop(session, notification.workshop_id)
    if quote is None or order is None or client is None or workshop is None:
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
    snapshot = quote.vehicle_snapshot or {}
    vehicle = " · ".join(
        part
        for part in (
            snapshot.get("plate"),
            " ".join(p for p in (snapshot.get("make"), snapshot.get("model")) if p),
        )
        if part
    )
    notice = NoticeContext(
        language=Language(client.language),
        workshop_name=workshop.name,
        reply_to=workshop.reply_to_email,
        order_code=order_code(order.year, order.number),
        vehicle=vehicle,
        link=order_link(
            get_settings().app_url, workshop.id, workshop.portal_slug, order.id
        ),
    )
    return quote, notice, client, workshop.timezone


async def compose_quote_sent(
    session: AsyncSession, notification: Notification
) -> Email | NotDelivered:
    found = await _context(session, notification)
    if isinstance(found, NotDelivered):
        return found
    quote, notice, client, timezone = found
    now = await notification_repo.db_now(session)
    # Sigue esperando respuesta y en plazo: si el cliente ya decidió, o el taller
    # la sustituyó o la anuló, este aviso ya no tiene sentido.
    if (
        quote.status != QuoteStatus.SENT
        or quote.valid_until is None
        or quote.valid_until <= now
        or quote.total_cents is None
    ):
        return OBSOLETE
    assert client.email is not None
    return compose(
        client.email,
        quote_sent_email(
            notice,
            version_no=quote.version_no,
            total_cents=quote.total_cents,
            last_valid_day=last_valid_day(quote.valid_until, timezone),
        ),
    )


async def compose_quote_cancelled(
    session: AsyncSession, notification: Notification
) -> Email | NotDelivered:
    found = await _context(session, notification)
    if isinstance(found, NotDelivered):
        return found
    quote, notice, client, _ = found
    if quote.status != QuoteStatus.CANCELLED:
        return OBSOLETE
    # "Si ya lo había recibido" (§6): el aviso de esa versión salió, o pudo salir.
    sent = await notification_repo.status_of_key(session, sent_key(quote))
    if sent not in (NotificationStatus.SENT, NotificationStatus.UNKNOWN):
        return OBSOLETE
    assert client.email is not None
    return compose(
        client.email, quote_cancelled_email(notice, version_no=quote.version_no)
    )
