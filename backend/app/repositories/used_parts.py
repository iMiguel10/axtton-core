"""Las piezas usadas en las órdenes del taller fijado (F7 paso 3), bajo RLS."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.inventory import MovementKind
from app.models import Employee, StockMovement, UsedPart


async def get_for_update(
    session: AsyncSession, order_id: UUID, used_part_id: UUID
) -> UsedPart | None:
    """La pieza usada de esa orden, bloqueada: dos que la quitan a la vez van
    una detrás de otra, y la segunda la ve ya quitada."""
    query = (
        select(UsedPart)
        .where(UsedPart.id == used_part_id, UsedPart.work_order_id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(query)).one_or_none()


async def count_mounted(session: AsyncSession, order_id: UUID) -> int:
    """Las piezas montadas y sin quitar: las que impiden cancelar (§6)."""
    count = await session.scalar(
        select(func.count()).where(
            UsedPart.work_order_id == order_id, UsedPart.removed_at.is_(None)
        )
    )
    return count or 0


async def outflow_of(session: AsyncSession, used_part_id: UUID) -> StockMovement | None:
    """La salida de stock de una pieza usada, si la tuvo (la pieza se contaba
    al montarla). Hay una como mucho (uq_stock_movements_used_part_id_out)."""
    return (
        await session.scalars(
            select(StockMovement).where(
                StockMovement.used_part_id == used_part_id,
                StockMovement.kind == MovementKind.OUT,
            )
        )
    ).one_or_none()


@dataclass(frozen=True)
class UsedPartRow:
    used_part: UsedPart
    employee_name: str
    removed_by_name: str | None


async def list_for_order(session: AsyncSession, order_id: UUID) -> list[UsedPartRow]:
    """Las piezas de una orden, en el orden en que se montaron."""
    remover = aliased(Employee)
    rows = await session.execute(
        select(UsedPart, Employee.name, remover.name)
        .join(Employee, Employee.id == UsedPart.employee_id)
        .outerjoin(remover, remover.id == UsedPart.removed_by_employee_id)
        .where(UsedPart.work_order_id == order_id)
        .order_by(UsedPart.created_at, UsedPart.id)
    )
    return [UsedPartRow(used, name, removed_by) for used, name, removed_by in rows]
