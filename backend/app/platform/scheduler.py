"""El planificador del worker (arquitectura §4 y §8): qué hay pendiente en todos
los talleres.

Es una de las vías que cruzan talleres, y **solo busca**: devuelve ids de
talleres (o de filas con su taller), nunca las procesa. Cada trabajo se hace
después en la transacción de su taller, con axtton_app y RLS (`services/`), así
que un fallo al procesar no puede tocar otro taller.
"""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select

from app.domain.notifications import NotificationStatus
from app.domain.quotes import QuoteStatus
from app.models import Notification, PortalLink, Quote
from app.platform.db import platform_transaction


async def workshops_with_expired_links(retention: timedelta) -> list[UUID]:
    """Los talleres con enlaces del portal caducados hace más de `retention`."""
    query = (
        select(PortalLink.workshop_id)
        .where(PortalLink.expires_at < func.clock_timestamp() - retention)
        .distinct()
    )
    async with platform_transaction() as session:
        return list(await session.scalars(query))


async def workshops_with_overdue_quotes() -> list[UUID]:
    """Los talleres con versiones enviadas cuya validez ya pasó (F5 paso 2)."""
    query = (
        select(Quote.workshop_id)
        .where(
            Quote.status == QuoteStatus.SENT,
            Quote.valid_until <= func.clock_timestamp(),
        )
        .distinct()
    )
    async with platform_transaction() as session:
        return list(await session.scalars(query))


async def workshops_with_due_notifications() -> list[UUID]:
    """Los talleres con avisos que toca enviar: pendientes con su hora ya
    llegada, o fallidos con su reintento vencido (F5 paso 4)."""
    now = func.clock_timestamp()
    query = (
        select(Notification.workshop_id)
        .where(
            or_(
                and_(
                    Notification.status == NotificationStatus.PENDING,
                    Notification.scheduled_for <= now,
                ),
                and_(
                    Notification.status == NotificationStatus.FAILED,
                    Notification.next_attempt_at <= now,
                ),
            )
        )
        .distinct()
    )
    async with platform_transaction() as session:
        return list(await session.scalars(query))


async def workshops_with_abandoned_notifications(older_than: timedelta) -> list[UUID]:
    """Los talleres con avisos reclamados hace más de `older_than` (F5 paso 4)."""
    query = (
        select(Notification.workshop_id)
        .where(
            Notification.status == NotificationStatus.CLAIMED,
            Notification.claimed_at < func.clock_timestamp() - older_than,
        )
        .distinct()
    )
    async with platform_transaction() as session:
        return list(await session.scalars(query))
