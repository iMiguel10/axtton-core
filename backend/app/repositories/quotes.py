"""Presupuestos de una orden (F3), bajo RLS: los de otro taller no existen."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.quotes import QuoteStatus
from app.domain.work_orders import CLOSED
from app.models import (
    Client,
    DiagnosisVersion,
    Quote,
    QuoteLine,
    Vehicle,
    WorkOrder,
)


async def list_for_order(session: AsyncSession, order_id: UUID) -> list[Quote]:
    """Las versiones de una orden, de la más nueva a la más antigua."""
    query = (
        select(Quote)
        .where(Quote.work_order_id == order_id)
        .order_by(Quote.version_no.desc())
    )
    return list(await session.scalars(query))


async def lines_of(
    session: AsyncSession, quote_ids: list[UUID]
) -> dict[UUID, list[QuoteLine]]:
    if not quote_ids:
        return {}
    query = (
        select(QuoteLine)
        .where(QuoteLine.quote_id.in_(quote_ids))
        .order_by(QuoteLine.quote_id, QuoteLine.position)
    )
    grouped: dict[UUID, list[QuoteLine]] = defaultdict(list)
    for line in await session.scalars(query):
        grouped[line.quote_id].append(line)
    return grouped


async def get(session: AsyncSession, quote_id: UUID) -> Quote | None:
    return await session.get(Quote, quote_id)


async def get_for_update(session: AsyncSession, quote_id: UUID) -> Quote | None:
    """La versión, bloqueada hasta el final de la transacción y leída de nuevo
    (`populate_existing`): no se compara la versión con lo leído antes del
    bloqueo."""
    query = (
        select(Quote)
        .where(Quote.id == quote_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(query)).one_or_none()


async def versions_count(session: AsyncSession, order_id: UUID) -> int:
    query = select(func.count()).where(Quote.work_order_id == order_id)
    return int(await session.scalar(query) or 0)


async def latest(session: AsyncSession, order_id: UUID) -> Quote | None:
    query = (
        select(Quote)
        .where(Quote.work_order_id == order_id)
        .order_by(Quote.version_no.desc())
        .limit(1)
    )
    return (await session.scalars(query)).one_or_none()


async def has_draft(session: AsyncSession, order_id: UUID) -> bool:
    query = select(Quote.id).where(
        Quote.work_order_id == order_id, Quote.status == QuoteStatus.DRAFT
    )
    return (await session.scalar(query.limit(1))) is not None


async def delete_lines(session: AsyncSession, quote_id: UUID) -> None:
    """Borra las líneas de un borrador (el trigger lo impide en uno enviado)."""
    await session.execute(
        delete(QuoteLine)
        .where(QuoteLine.quote_id == quote_id)
        .execution_options(synchronize_session=False)
    )


@dataclass(frozen=True)
class QuoteRow:
    quote: Quote
    order: WorkOrder
    plate: str
    client_name: str


ListView = Literal["pending", "expired", "drafts", "all"]


async def list_page(
    session: AsyncSession, *, view: ListView, limit: int, offset: int
) -> list[QuoteRow]:
    """Los presupuestos del taller fijado, con su orden, matrícula y cliente.

    Cada orden tiene como mucho una versión enviada y un borrador (índices
    únicos parciales), así que "pendientes", "caducados" y "borradores" dan
    una fila por orden filtrando por estado. "Todos" da la versión más reciente
    de cada orden: las anteriores están en su ficha.
    """
    now = func.clock_timestamp()
    statement = (
        select(Quote, WorkOrder, Vehicle.plate, Client.name)
        .join(WorkOrder, WorkOrder.id == Quote.work_order_id)
        .join(Vehicle, Vehicle.id == WorkOrder.vehicle_id)
        .join(Client, Client.id == WorkOrder.client_id)
    )
    match view:
        case "pending":
            # Esperando al cliente y aún en plazo: los que caducan antes, primero.
            statement = statement.where(
                Quote.status == QuoteStatus.SENT, Quote.valid_until > now
            ).order_by(Quote.valid_until, Quote.id)
        case "expired":
            # Pasado su plazo aunque nadie la haya marcado (hasta el worker, F5,
            # nadie escribe `expired`): hay que reenviarla o anularla (§6).
            statement = statement.where(
                or_(
                    Quote.status == QuoteStatus.EXPIRED,
                    and_(Quote.status == QuoteStatus.SENT, Quote.valid_until <= now),
                )
            ).order_by(Quote.valid_until.desc(), Quote.id)
        case "drafts":
            # Un borrador que quedó en una orden cerrada ya no se enviará.
            statement = statement.where(
                Quote.status == QuoteStatus.DRAFT, WorkOrder.status.not_in(CLOSED)
            ).order_by(Quote.updated_at.desc(), Quote.id)
        case "all":
            latest = (
                select(Quote.id)
                .ext(distinct_on(Quote.work_order_id))
                .order_by(Quote.work_order_id, Quote.version_no.desc())
                .subquery()
            )
            statement = statement.join(latest, latest.c.id == Quote.id).order_by(
                Quote.updated_at.desc(), Quote.id
            )
    rows = await session.execute(statement.limit(limit).offset(offset))
    return [QuoteRow(quote, order, plate, name) for quote, order, plate, name in rows]


async def awaiting_version(session: AsyncSession, order_id: UUID) -> Quote | None:
    """La versión que espera respuesta del cliente: la enviada (como mucho una,
    por el índice único parcial) o, si ya se marcó como caducada, esa. Es la
    que una versión nueva sustituye."""
    query = (
        select(Quote)
        .where(
            Quote.work_order_id == order_id,
            Quote.status.in_([QuoteStatus.SENT, QuoteStatus.EXPIRED]),
        )
        .order_by(Quote.version_no.desc())
        .limit(1)
    )
    return (await session.scalars(query)).one_or_none()


async def count_not_draft(session: AsyncSession, order_id: UUID) -> int:
    """Cuántas versiones se han enviado alguna vez (cualquier estado que no sea
    borrador): una orden así no se cancela (§6)."""
    query = select(func.count()).where(
        Quote.work_order_id == order_id, Quote.status != QuoteStatus.DRAFT
    )
    return int(await session.scalar(query) or 0)


async def latest_diagnosis_id(session: AsyncSession, order_id: UUID) -> UUID | None:
    """La versión vigente del diagnóstico para el cliente (RF-22): la que
    acompaña al envío."""
    query = (
        select(DiagnosisVersion.id)
        .where(DiagnosisVersion.work_order_id == order_id)
        .order_by(DiagnosisVersion.version_no.desc())
        .limit(1)
    )
    return await session.scalar(query)
