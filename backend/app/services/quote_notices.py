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

from app.domain.business_days import last_valid_day
from app.domain.emails import quote_cancelled_email, quote_sent_email
from app.domain.notifications import (
    NotificationKind,
    NotificationStatus,
)
from app.domain.quotes import QuoteStatus
from app.infra.email import Email, compose
from app.models import Notification, Quote, WorkOrder
from app.repositories import notifications as notification_repo
from app.repositories import quotes as quote_repo
from app.services import notice_context
from app.services import notifications as notification_service
from app.services.notifications import NotDelivered

OBSOLETE = notice_context.OBSOLETE


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


async def _quote_and_recipient(
    session: AsyncSession, notification: Notification
) -> tuple[Quote, notice_context.Recipient] | NotDelivered:
    assert notification.quote_id is not None
    quote = await quote_repo.get(session, notification.quote_id)
    if quote is None:
        return OBSOLETE
    found = await notice_context.load(session, notification)
    if isinstance(found, NotDelivered):
        return found
    return quote, found


async def compose_quote_sent(
    session: AsyncSession, notification: Notification
) -> Email | NotDelivered:
    found = await _quote_and_recipient(session, notification)
    if isinstance(found, NotDelivered):
        return found
    quote, recipient = found
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
    # El vehículo y los km congelados al enviar, como en el PDF (RF-55).
    notice = notice_context.notice_for(
        recipient, notice_context.vehicle_label(quote.vehicle_snapshot)
    )
    return compose(
        recipient.email,
        quote_sent_email(
            notice,
            version_no=quote.version_no,
            total_cents=quote.total_cents,
            last_valid_day=last_valid_day(
                quote.valid_until, recipient.workshop.timezone
            ),
        ),
    )


async def compose_quote_cancelled(
    session: AsyncSession, notification: Notification
) -> Email | NotDelivered:
    found = await _quote_and_recipient(session, notification)
    if isinstance(found, NotDelivered):
        return found
    quote, recipient = found
    if quote.status != QuoteStatus.CANCELLED:
        return OBSOLETE
    # "Si ya lo había recibido" (§6): el aviso de esa versión salió, o pudo salir.
    sent = await notification_repo.status_of_key(session, sent_key(quote))
    if sent not in (NotificationStatus.SENT, NotificationStatus.UNKNOWN):
        return OBSOLETE
    notice = notice_context.notice_for(
        recipient, notice_context.vehicle_label(quote.vehicle_snapshot)
    )
    return compose(
        recipient.email, quote_cancelled_email(notice, version_no=quote.version_no)
    )
