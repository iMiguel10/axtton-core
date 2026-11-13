"""La bandeja de avisos al cliente (F5 paso 4, arquitectura §8, RF-62).

Cuatro piezas:

- **Crear** un aviso (`create`): en la transacción del cambio que lo provoca,
  nunca después (invariante 8). Si el cambio se deshace, el aviso también.
- **Despachar** (`dispatch`, cada minuto): reclamar lo que toca enviar,
  confirmarlo y, ya confirmado, encolar un envío por aviso con su número de
  intento. Si la cola no responde, se deshace el reclamo y vuelve a esperar;
  la clave del trabajo lleva la hora del reclamo, así que el reclamo siguiente
  nunca choca en SAQ con un trabajo del anterior.
- **Enviar** (`deliver`, un trabajo por aviso): con la fila bloqueada hasta
  guardar el resultado, SMTP incluido, y solo si sigue reclamada con ese mismo
  intento. El resultado del envío decide el estado: solo se reintenta lo que con
  seguridad no salió.
- **Reclamos abandonados** (`expire_abandoned`, cada diez minutos): `unknown`,
  sin reenviar.

Cada paso trabaja en la transacción de un taller, con axtton_app y RLS: un
trabajo con el taller equivocado no ve el aviso (B2).
"""

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import workshop_transaction
from app.domain.notifications import (
    ABANDONED_AFTER,
    FailureReason,
    NotificationKind,
    NotificationStatus,
    next_attempt_at,
)
from app.infra.email import (
    Email,
    EmailDeliveryUnknownError,
    EmailNotSentError,
    EmailSender,
)
from app.infra.queue import JobQueue, QueueUnavailableError
from app.models import Notification
from app.repositories import notifications as notification_repo

logger = logging.getLogger(__name__)

SEND_NOTIFICATION = "send_notification"
# Un correo: hasta tres pasos de 20 s de SMTP (config.smtp_timeout_seconds) y un
# solo intento en la cola. Quien decide si se reintenta es el estado del aviso,
# que sabe dónde falló; un reintento de SAQ podría duplicarlo.
SEND_TIMEOUT_SECONDS = 60
# Cuántos avisos reclama una pasada por taller; lo demás, en la siguiente.
DISPATCH_BATCH = 100


@dataclass(frozen=True)
class NotDelivered:
    """Lo que dice un compositor cuando no hay que enviar nada: `cancelled` (lo
    que avisaba ya no existe) o `skipped` (no se le puede avisar: sin email)."""

    status: NotificationStatus
    reason: FailureReason


# El compositor de un tipo de aviso: vuelve a comprobar que el motivo sigue
# vigente (arquitectura §8, "doble comprobación al enviar") y escribe el correo,
# o dice por qué no hay que enviarlo. Corre en la transacción del envío, con el
# aviso bloqueado. Los de cada tipo, en `services/notice_composers.py`.
Composer = Callable[[AsyncSession, Notification], Awaitable[Email | NotDelivered]]


async def create(
    session: AsyncSession,
    *,
    workshop_id: UUID,
    kind: NotificationKind,
    dedupe_key: str,
    client_id: UUID,
    work_order_id: UUID | None = None,
    quote_id: UUID | None = None,
) -> bool:
    """Crea el aviso en la transacción en curso, la del cambio que lo provoca
    (invariante 8). Dice si lo creó: el mismo motivo no se repite (RF-62)."""
    return await notification_repo.add(
        session,
        workshop_id=workshop_id,
        kind=kind,
        dedupe_key=dedupe_key,
        client_id=client_id,
        work_order_id=work_order_id,
        quote_id=quote_id,
    )


async def dispatch(workshop_id: UUID, queue: JobQueue, email_enabled: bool) -> int:
    """Una pasada del despachador en un taller. Devuelve cuántos avisos encoló (o,
    sin SMTP, cuántos marcó `skipped`)."""
    if not email_enabled:
        async with workshop_transaction([workshop_id]) as session:
            return await notification_repo.skip_due(
                session, FailureReason.EMAIL_DISABLED
            )

    # El reclamo se confirma antes de encolar: el envío puede empezar antes de
    # que `enqueue` vuelva, y tiene que encontrar el aviso ya reclamado.
    async with workshop_transaction([workshop_id]) as session:
        claimed = await notification_repo.claim_due(session, DISPATCH_BATCH)

    enqueued = 0
    for notification_id, attempt, claimed_at in claimed:
        try:
            await queue.enqueue(
                SEND_NOTIFICATION,
                timeout_seconds=SEND_TIMEOUT_SECONDS,
                max_attempts=1,
                # Una clave por reclamo: dos encolados del mismo reclamo son uno, y
                # otro reclamo es otro trabajo aunque repita el número de intento
                # (deshacer un reclamo lo devuelve). SAQ recuerda una clave unos
                # 10 minutos: con la de un reclamo deshecho, descartaría el nuevo.
                key=f"notification:{notification_id}:{claimed_at.timestamp():.6f}",
                workshop_id=str(workshop_id),
                notification_id=str(notification_id),
                attempt=attempt,
            )
        except QueueUnavailableError:
            # Seguro aunque el trabajo hubiera llegado a la cola: si se ejecuta
            # antes del reclamo siguiente, encuentra el aviso pendiente y no hace
            # nada; si después, lo envía, y el del reclamo nuevo lo encuentra
            # enviado. Un correo, como mucho.
            logger.warning("Aviso %s sin encolar: vuelve a esperar", notification_id)
            async with workshop_transaction([workshop_id]) as session:
                await notification_repo.unclaim(session, notification_id, attempt)
        else:
            enqueued += 1
    return enqueued


def _finish(
    notification: Notification,
    status: NotificationStatus,
    reason: FailureReason | None = None,
    smtp_code: int | None = None,
) -> None:
    notification.status = status
    notification.claimed_at = None
    notification.failure_reason = reason
    notification.smtp_code = smtp_code


async def deliver(
    workshop_id: UUID,
    notification_id: UUID,
    attempt: int,
    sender: EmailSender,
    composers: Mapping[NotificationKind, Composer],
) -> NotificationStatus | None:
    """Envía un aviso reclamado y guarda el resultado. Devuelve el estado en que
    lo deja, o None si no le tocaba a esta ejecución.

    La fila queda bloqueada hasta el commit, con la conversación SMTP dentro: si
    este mismo envío se ejecuta dos veces a la vez, la segunda ejecución se salta
    la fila; si llega después, ya no está reclamada con este intento (B1, B3).
    Si el commit fallara después de enviar, el aviso se quedaría reclamado y el
    barrido de abandonados lo daría por `unknown`: nunca se reenvía.
    """
    async with workshop_transaction([workshop_id]) as session:
        notification = await notification_repo.get_for_delivery(
            session, notification_id
        )
        if (
            notification is None
            or notification.status != NotificationStatus.CLAIMED
            or notification.attempts != attempt
        ):
            logger.info(
                "Aviso %s, intento %d: nada que hacer", notification_id, attempt
            )
            return None

        composer = composers.get(NotificationKind(notification.kind))
        if composer is None:
            logger.error(
                "Aviso %s de tipo %s sin compositor", notification_id, notification.kind
            )
            _finish(notification, NotificationStatus.FAILED, FailureReason.NO_COMPOSER)
            return NotificationStatus.FAILED

        try:
            # En un savepoint: si falla por un error de SQL, la transacción no
            # queda abortada y aún se puede guardar el fallo. El bloqueo de la
            # fila es de antes del savepoint y sigue en pie.
            async with session.begin_nested():
                composed = await composer(session, notification)
        except Exception:
            # Antes de hablar con el servidor: no salió nada, se puede reintentar.
            logger.exception("Aviso %s: falló al escribirlo", notification_id)
            return await _failed(session, notification, FailureReason.COMPOSE_FAILED)

        if isinstance(composed, NotDelivered):
            _finish(notification, composed.status, composed.reason)
            return composed.status
        if not sender.enabled:
            _finish(
                notification, NotificationStatus.SKIPPED, FailureReason.EMAIL_DISABLED
            )
            return NotificationStatus.SKIPPED

        try:
            await sender.send(composed)
        except EmailDeliveryUnknownError as exc:
            logger.warning("Aviso %s: no se sabe si salió (%s)", notification_id, exc)
            _finish(
                notification,
                NotificationStatus.UNKNOWN,
                FailureReason.DELIVERY_UNKNOWN,
                exc.smtp_code,
            )
            return NotificationStatus.UNKNOWN
        except EmailNotSentError as exc:
            logger.warning("Aviso %s no enviado (%s)", notification_id, exc)
            return await _failed(
                session, notification, FailureReason.NOT_SENT, exc.smtp_code
            )
        except Exception:
            # Un error sin clasificar al enviar: puede que saliera. Lo prudente es
            # no reintentarlo (RF-62).
            logger.exception(
                "Aviso %s: error sin clasificar al enviar", notification_id
            )
            _finish(
                notification, NotificationStatus.UNKNOWN, FailureReason.DELIVERY_UNKNOWN
            )
            return NotificationStatus.UNKNOWN

        # La hora antes de tocar el aviso: leerla después provocaría un
        # autoflush de un `sent` aún sin `sent_at`, y el CHECK lo rechazaría.
        sent_at = await notification_repo.db_now(session)
        _finish(notification, NotificationStatus.SENT)
        notification.sent_at = sent_at
        logger.info("Aviso %s enviado", notification_id)
        return NotificationStatus.SENT


async def _failed(
    session: AsyncSession,
    notification: Notification,
    reason: FailureReason,
    smtp_code: int | None = None,
) -> NotificationStatus:
    """No salió: `failed`, con su reintento si quedan intentos (B5)."""
    now = await notification_repo.db_now(session)
    _finish(notification, NotificationStatus.FAILED, reason, smtp_code)
    notification.next_attempt_at = next_attempt_at(notification.attempts, now)
    return NotificationStatus.FAILED


async def expire_abandoned(workshop_id: UUID) -> int:
    """Los reclamos de un taller sin resultado pasado ABANDONED_AFTER pasan a
    `unknown` y no se reenvían (B6)."""
    async with workshop_transaction([workshop_id]) as session:
        expired = await notification_repo.expire_abandoned(session, ABANDONED_AFTER)
    if expired:
        logger.warning("%d avisos abandonados pasan a unknown", expired)
    return expired
