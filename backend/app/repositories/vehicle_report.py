"""Lo que lee el informe de actuaciones de un vehículo (F6 paso 5, RF-18).

Todas las órdenes del vehículo, de cualquier titular, con lo de cada una en una
consulta por tipo de dato, nunca una por orden: con cien órdenes, el informe
tiene que salir en menos de 10 s (RNF-52).
"""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.quotes import QuoteStatus
from app.domain.work_orders import WorkOrderStatus
from app.models import Client, DiagnosisVersion, Quote, WorkEntry, WorkOrder


async def orders_of(
    session: AsyncSession, vehicle_id: UUID
) -> list[tuple[WorkOrder, str]]:
    """Las órdenes del vehículo, sin las canceladas (nunca se hizo nada en
    ellas), de la más antigua a la más reciente, con el nombre de su cliente
    (vacío si se anonimizó)."""
    rows = await session.execute(
        select(WorkOrder, Client.name)
        .join(Client, Client.id == WorkOrder.client_id)
        .where(
            WorkOrder.vehicle_id == vehicle_id,
            WorkOrder.status != WorkOrderStatus.CANCELLED,
        )
        .order_by(WorkOrder.created_at, WorkOrder.year, WorkOrder.number)
    )
    return [(order, name) for order, name in rows]


async def current_diagnoses(
    session: AsyncSession, order_ids: list[UUID]
) -> dict[UUID, str]:
    """El texto vigente del diagnóstico de cada orden (el de `version_no` más
    alto), el que se redacta para el cliente (RF-22)."""
    if not order_ids:
        return {}
    rows = await session.execute(
        select(DiagnosisVersion.work_order_id, DiagnosisVersion.text)
        .where(DiagnosisVersion.work_order_id.in_(order_ids))
        .order_by(DiagnosisVersion.work_order_id, DiagnosisVersion.version_no.desc())
        .ext(distinct_on(DiagnosisVersion.work_order_id))
    )
    return {order_id: text for order_id, text in rows}


async def work_entries_of(
    session: AsyncSession, order_ids: list[UUID]
) -> dict[UUID, list[WorkEntry]]:
    """Los trabajos sin anular de cada orden, por el día en que se hicieron."""
    if not order_ids:
        return {}
    query = (
        select(WorkEntry)
        .where(WorkEntry.work_order_id.in_(order_ids), WorkEntry.voided_at.is_(None))
        .order_by(WorkEntry.work_order_id, WorkEntry.worked_on, WorkEntry.created_at)
    )
    grouped: dict[UUID, list[WorkEntry]] = defaultdict(list)
    for entry in await session.scalars(query):
        grouped[entry.work_order_id].append(entry)
    return grouped


async def last_approved_of(
    session: AsyncSession, order_ids: list[UUID]
) -> dict[UUID, Quote]:
    """La última versión aprobada de cada orden, como `quotes.last_approved`."""
    if not order_ids:
        return {}
    query = (
        select(Quote)
        .where(
            Quote.work_order_id.in_(order_ids),
            Quote.status == QuoteStatus.APPROVED,
        )
        .order_by(Quote.work_order_id, Quote.version_no.desc())
        .ext(distinct_on(Quote.work_order_id))
    )
    return {quote.work_order_id: quote for quote in await session.scalars(query)}
