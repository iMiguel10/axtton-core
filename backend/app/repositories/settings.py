"""Configuración del taller activo (RF-02), bajo RLS: solo existe la suya."""

from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LaborRate, Workshop, WorkshopLogo


async def get_workshop(session: AsyncSession, workshop_id: UUID) -> Workshop | None:
    return await session.get(Workshop, workshop_id)


async def get_logo(session: AsyncSession, workshop_id: UUID) -> WorkshopLogo | None:
    return await session.get(WorkshopLogo, workshop_id)


async def has_logo(session: AsyncSession, workshop_id: UUID) -> bool:
    # Sin leer la imagen: solo si existe.
    found = await session.scalar(
        select(WorkshopLogo.workshop_id).where(WorkshopLogo.workshop_id == workshop_id)
    )
    return found is not None


async def lock_labor_rates(session: AsyncSession, workshop_id: UUID) -> None:
    """Pone en fila, hasta el final de la transacción, lo que cambia las tarifas
    de un taller en conjunto: cuál es la de por defecto y cuántas hay vigentes.

    Sin esto, dos que marcan a la vez tarifas distintas como de por defecto
    quitan cada uno la marca de la anterior sin ver al otro (READ COMMITTED), y
    el segundo choca con el índice único: un 409 donde debería ganar el último.
    Bloqueo consultivo, como employee_repo.lock_staff.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"labor_rates:{workshop_id}"},
    )


async def list_labor_rates(session: AsyncSession, *, archived: bool) -> list[LaborRate]:
    condition = (
        LaborRate.archived_at.is_not(None)
        if archived
        else LaborRate.archived_at.is_(None)
    )
    query = select(LaborRate).where(condition).order_by(LaborRate.name, LaborRate.id)
    return list(await session.scalars(query))


async def get_labor_rate(session: AsyncSession, rate_id: UUID) -> LaborRate | None:
    return await session.get(LaborRate, rate_id)


async def active_labor_rates(session: AsyncSession) -> int:
    query = select(func.count()).where(LaborRate.archived_at.is_(None))
    return int(await session.scalar(query) or 0)


async def name_taken(
    session: AsyncSession, name: str, *, except_id: UUID | None = None
) -> bool:
    query = select(LaborRate.id).where(
        func.lower(LaborRate.name) == name.lower(), LaborRate.archived_at.is_(None)
    )
    if except_id is not None:
        query = query.where(LaborRate.id != except_id)
    return (await session.scalar(query.limit(1))) is not None


async def clear_default(
    session: AsyncSession, *, except_id: UUID | None = None
) -> None:
    """Quita la marca de la de por defecto anterior. Sin subir su `version`: no
    es un cambio que alguien estuviera editando, y no debe darle un 409."""
    query = update(LaborRate).where(LaborRate.is_default).values(is_default=False)
    if except_id is not None:
        query = query.where(LaborRate.id != except_id)
    await session.execute(query.execution_options(synchronize_session="fetch"))
