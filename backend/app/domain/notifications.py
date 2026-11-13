"""La bandeja de avisos al cliente (F5 paso 4, arquitectura §8): tipos, estados,
transiciones y reintentos. Sin I/O.

Un aviso es una fila de `notifications` que nace en la misma transacción que el
cambio que lo provoca (invariante 8) y que el worker envía después. "Nunca dos
veces por el mismo motivo" (RF-62) lo dan, juntos:

- la `dedupe_key`, única por taller: el mismo motivo es la misma fila;
- reintentar solo lo que con seguridad no salió (`failed`), nunca lo que pudo
  salir (`unknown`);
- y que `sent` y `unknown` sean finales, también para la base de datos (trigger
  `notifications_transitions`, migración 0022outbox).
"""

from datetime import datetime, timedelta
from enum import StrEnum


class NotificationKind(StrEnum):
    """Los avisos de F5 (RF-60). Los de citas y vencimientos llegan en F8."""

    QUOTE_SENT = "quote_sent"
    QUOTE_CANCELLED = "quote_cancelled"
    VEHICLE_READY = "vehicle_ready"


class NotificationStatus(StrEnum):
    PENDING = "pending"  # creado; espera a su hora (`scheduled_for`)
    CLAIMED = "claimed"  # el despachador lo reclamó y encoló su envío
    SENT = "sent"  # el servidor SMTP lo aceptó
    FAILED = "failed"  # no salió; se reintenta si quedan intentos
    UNKNOWN = "unknown"  # pudo salir: nunca se reintenta
    CANCELLED = "cancelled"  # lo que avisaba ya no existe
    SKIPPED = "skipped"  # no se puede avisar (sin email, sin correo)


class FailureReason(StrEnum):
    """Por qué un aviso no salió, o por qué no se sabe si salió (RF-69). Nunca el
    texto del servidor: puede llevar el email del cliente (RNF-40)."""

    # skipped
    NO_EMAIL = "no_email"  # el cliente no tiene email (RF-63)
    EMAIL_DISABLED = "email_disabled"  # la instalación no tiene SMTP (RNF-32)
    # cancelled
    OBSOLETE = "obsolete"  # el motivo ya no existe (doble comprobación, §8)
    # failed
    NOT_SENT = "not_sent"  # el servidor lo rechazó o no se pudo conectar
    COMPOSE_FAILED = "compose_failed"  # falló al escribirlo, antes del SMTP
    NO_COMPOSER = "no_composer"  # un tipo sin compositor: un fallo del código
    # unknown
    DELIVERY_UNKNOWN = "delivery_unknown"  # corte con el mensaje en vuelo
    ABANDONED = "abandoned"  # reclamado y nunca terminado (proceso muerto)


# Cuántas veces se intenta, la primera incluida.
MAX_ATTEMPTS = 3
# La espera tras el primer y el segundo fallo.
RETRY_DELAYS = (timedelta(minutes=5), timedelta(minutes=30))
# Un reclamo sin resultado pasado este tiempo se da por abandonado: el envío
# tiene un timeout de 60 s, así que diez minutos es que el proceso murió.
ABANDONED_AFTER = timedelta(minutes=10)

FINAL = frozenset(
    {
        NotificationStatus.SENT,
        NotificationStatus.UNKNOWN,
        NotificationStatus.CANCELLED,
        NotificationStatus.SKIPPED,
    }
)

# Las transiciones; las repite el trigger notifications_transitions.
TRANSITIONS: dict[NotificationStatus, frozenset[NotificationStatus]] = {
    NotificationStatus.PENDING: frozenset(
        {
            NotificationStatus.CLAIMED,
            NotificationStatus.CANCELLED,
            NotificationStatus.SKIPPED,
        }
    ),
    NotificationStatus.CLAIMED: frozenset(
        {
            NotificationStatus.PENDING,  # deshacer el reclamo si no se pudo encolar
            NotificationStatus.SENT,
            NotificationStatus.FAILED,
            NotificationStatus.UNKNOWN,
            NotificationStatus.CANCELLED,
            NotificationStatus.SKIPPED,
        }
    ),
    # Sin SMTP, un reintento pendiente ya no saldrá: `skipped`.
    NotificationStatus.FAILED: frozenset(
        {
            NotificationStatus.CLAIMED,
            NotificationStatus.CANCELLED,
            NotificationStatus.SKIPPED,
        }
    ),
}


def next_attempt_at(attempts: int, now: datetime) -> datetime | None:
    """Cuándo se reintenta un aviso que falló tras `attempts` intentos; None si ya
    no quedan."""
    if attempts >= MAX_ATTEMPTS:
        return None
    return now + RETRY_DELAYS[attempts - 1]
