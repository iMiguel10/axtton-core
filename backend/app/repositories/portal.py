"""Lo que lee el portal de las órdenes de un cliente (F4 paso 4, RF-42 a RF-44).

RLS separa talleres, no clientes: dentro de un taller, que un cliente solo vea lo
suyo lo garantiza este módulo (arquitectura §4, T4). Por eso las dos consultas
que abren la puerta exigen `client_id`, que sale siempre de la sesión. El acceso
va por la orden, nunca por el vehículo (invariante 7): quien compra un coche de
segunda mano no ve las reparaciones del dueño anterior (RF-44).

Las demás reciben una orden ya comprobada con `order_of`.
"""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.quotes import QuoteStatus
from app.models import DiagnosisVersion, Quote, Vehicle, WorkEntry, WorkOrder


def _orders_of(client_id: UUID) -> Select[WorkOrder, Vehicle]:
    return (
        select(WorkOrder, Vehicle)
        .join(Vehicle, Vehicle.id == WorkOrder.vehicle_id)
        .where(WorkOrder.client_id == client_id)
    )


async def orders_of(
    session: AsyncSession, client_id: UUID
) -> list[tuple[WorkOrder, Vehicle]]:
    """Las órdenes de las que fue cliente, las últimas primero."""
    rows = await session.execute(
        _orders_of(client_id).order_by(WorkOrder.year.desc(), WorkOrder.number.desc())
    )
    return [(order, vehicle) for order, vehicle in rows]


async def order_of(
    session: AsyncSession, client_id: UUID, order_id: UUID
) -> tuple[WorkOrder, Vehicle] | None:
    """Esa orden, solo si es de ese cliente."""
    row = (
        await session.execute(_orders_of(client_id).where(WorkOrder.id == order_id))
    ).one_or_none()
    return None if row is None else (row[0], row[1])


async def current_diagnosis(
    session: AsyncSession, order_id: UUID
) -> DiagnosisVersion | None:
    """La versión vigente del texto para el cliente (RF-22)."""
    query = (
        select(DiagnosisVersion)
        .where(DiagnosisVersion.work_order_id == order_id)
        .order_by(DiagnosisVersion.version_no.desc())
        .limit(1)
    )
    return (await session.scalars(query)).one_or_none()


async def sent_quotes(session: AsyncSession, order_id: UUID) -> list[Quote]:
    """Las versiones que se enviaron alguna vez, de la más nueva a la más antigua.
    Un borrador no ha salido del taller."""
    query = (
        select(Quote)
        .where(Quote.work_order_id == order_id, Quote.status != QuoteStatus.DRAFT)
        .order_by(Quote.version_no.desc())
    )
    return list(await session.scalars(query))


async def work_done(session: AsyncSession, order_id: UUID) -> list[WorkEntry]:
    """Los trabajos realizados: uno anulado es uno que no se hizo."""
    query = (
        select(WorkEntry)
        .where(WorkEntry.work_order_id == order_id, WorkEntry.voided_at.is_(None))
        .order_by(WorkEntry.worked_on, WorkEntry.created_at)
    )
    return list(await session.scalars(query))
