"""La bandeja de avisos (F5 paso 4), siempre bajo RLS con el taller fijado.

Las horas son las de la base de datos (`clock_timestamp()`), como en el resto de
caducidades: el worker y la API pueden no tener el mismo reloj.
"""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.notifications import (
    FailureReason,
    NotificationKind,
    NotificationStatus,
)
from app.models import Notification


async def db_now(session: AsyncSession) -> datetime:
    now = await session.scalar(select(func.clock_timestamp()))
    assert now is not None
    return now


async def add(
    session: AsyncSession,
    *,
    workshop_id: UUID,
    kind: NotificationKind,
    dedupe_key: str,
    client_id: UUID,
    work_order_id: UUID | None = None,
    quote_id: UUID | None = None,
) -> bool:
    """Crea el aviso si su motivo no existía, y dice si lo creó. El índice único
    es la última palabra: con dos transacciones a la vez, la segunda espera a la
    primera y no inserta nada (RF-62)."""
    statement = (
        insert(Notification)
        .values(
            workshop_id=workshop_id,
            kind=kind.value,
            dedupe_key=dedupe_key,
            client_id=client_id,
            work_order_id=work_order_id,
            quote_id=quote_id,
        )
        .on_conflict_do_nothing(constraint="uq_notifications_workshop_id_dedupe_key")
        .returning(Notification.id)
    )
    return (await session.scalar(statement)) is not None


def _due() -> ColumnElement[bool]:
    now = func.clock_timestamp()
    return or_(
        and_(
            Notification.status == NotificationStatus.PENDING,
            Notification.scheduled_for <= now,
        ),
        and_(
            Notification.status == NotificationStatus.FAILED,
            Notification.next_attempt_at <= now,
        ),
    )


async def claim_due(
    session: AsyncSession, limit: int
) -> list[tuple[UUID, int, datetime]]:
    """Reclama los avisos del taller que toca enviar (pendientes con su hora ya
    llegada, o fallidos con su reintento vencido) y devuelve cada id con su número
    de intento y la hora del reclamo. Cada reclamo suma un intento.

    `FOR UPDATE SKIP LOCKED`: dos despachadores a la vez se reparten las filas en
    vez de reclamar las mismas (B3); una fila que un envío tiene bloqueada no se
    toca.
    """
    due = (
        select(Notification.id)
        .where(_due())
        .order_by(Notification.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    statement = (
        update(Notification)
        .where(Notification.id.in_(due.scalar_subquery()))
        .values(
            status=NotificationStatus.CLAIMED,
            attempts=Notification.attempts + 1,
            claimed_at=func.clock_timestamp(),
            next_attempt_at=None,
            failure_reason=None,
            smtp_code=None,
        )
        .returning(Notification.id, Notification.attempts, Notification.claimed_at)
    )
    return [
        (row.id, row.attempts, row.claimed_at)
        for row in await session.execute(statement)
    ]


async def unclaim(session: AsyncSession, notification_id: UUID, attempt: int) -> bool:
    """Deshace un reclamo cuyo envío no se pudo encolar: vuelve a esperar, con el
    intento devuelto. Un primer intento vuelve a `pending`; un reintento, a
    `failed` con el reintento para ya. Solo si sigue reclamado con ese intento."""
    statement = (
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.status == NotificationStatus.CLAIMED,
            Notification.attempts == attempt,
        )
        .values(
            status=(
                NotificationStatus.PENDING
                if attempt == 1
                else NotificationStatus.FAILED
            ),
            attempts=attempt - 1,
            claimed_at=None,
            next_attempt_at=None if attempt == 1 else func.clock_timestamp(),
            failure_reason=None if attempt == 1 else FailureReason.NOT_SENT,
        )
        .returning(Notification.id)
    )
    return (await session.scalar(statement)) is not None


async def skip_due(session: AsyncSession, reason: FailureReason) -> int:
    """Sin SMTP (RNF-32): lo que tocaba enviar queda `skipped`, con el motivo."""
    due = select(Notification.id).where(_due()).with_for_update(skip_locked=True)
    result = await session.execute(
        update(Notification)
        .where(Notification.id.in_(due.scalar_subquery()))
        .values(
            status=NotificationStatus.SKIPPED,
            failure_reason=reason,
            next_attempt_at=None,
        )
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


async def get_for_delivery(
    session: AsyncSession, notification_id: UUID
) -> Notification | None:
    """El aviso, bloqueado hasta el final de la transacción, o None si otro envío
    lo tiene bloqueado (`SKIP LOCKED`): el mismo envío ejecutado dos veces a la
    vez sale una sola vez (B3)."""
    query = (
        select(Notification)
        .where(Notification.id == notification_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(query)).one_or_none()


async def expire_abandoned(session: AsyncSession, older_than: timedelta) -> int:
    """Los reclamados hace más de `older_than` pasan a `unknown` (B6): el proceso
    murió en algún punto, y pudo ser después de entregar. Se salta los que un
    envío tiene bloqueados: ese aún puede terminar."""
    abandoned = (
        select(Notification.id)
        .where(
            Notification.status == NotificationStatus.CLAIMED,
            Notification.claimed_at < func.clock_timestamp() - older_than,
        )
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(
        update(Notification)
        .where(Notification.id.in_(abandoned.scalar_subquery()))
        .values(
            status=NotificationStatus.UNKNOWN,
            claimed_at=None,
            failure_reason=FailureReason.ABANDONED,
        )
    )
    return int(result.rowcount)  # type: ignore[attr-defined]
