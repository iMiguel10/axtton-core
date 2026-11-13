"""Qué compositor escribe cada tipo de aviso (arquitectura §8).

Un tipo sin compositor no se envía: el aviso acaba `failed` sin más intentos
(`no_composer`), porque es un fallo del código, no del correo. Los de vehículo
listo llegan en F5 paso 6.
"""

from app.domain.notifications import NotificationKind
from app.services import quote_notices
from app.services.notifications import Composer

COMPOSERS: dict[NotificationKind, Composer] = {
    NotificationKind.QUOTE_SENT: quote_notices.compose_quote_sent,
    NotificationKind.QUOTE_CANCELLED: quote_notices.compose_quote_cancelled,
}
