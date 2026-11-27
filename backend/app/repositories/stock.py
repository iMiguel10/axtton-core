"""El libro de movimientos de stock del taller fijado (F7 paso 2), bajo RLS.

Solo se insertan filas (RNF-12): aquí no hay ningún UPDATE ni DELETE.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Employee, Part, StockMovement


async def lock_part(session: AsyncSession, part_id: UUID) -> Part | None:
    """La pieza, bloqueada en exclusiva hasta el final de la transacción. Lo
    pide el recuento (RF-92), que compara el stock con lo que vio quien contó.

    Tiene que ser `FOR UPDATE`, no `FOR NO KEY UPDATE`: lo que lo pone en fila
    con una entrada o una salida a la vez es el bloqueo que pone la FK de su
    movimiento sobre la pieza (`FOR KEY SHARE`), y ese solo choca con
    `FOR UPDATE`. Así, el recuento espera a los movimientos sin confirmar y
    suma después; y los que llegan durante el recuento esperan a que termine.
    Las entradas y salidas entre sí no se esperan nunca (RNF-13).
    """
    query = (
        select(Part)
        .where(Part.id == part_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(query)).one_or_none()


async def stock_of(session: AsyncSession, part_id: UUID) -> Decimal:
    """La suma de los movimientos de la pieza (invariante 9); 0 si no tiene."""
    value = await session.scalar(
        select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
            StockMovement.part_id == part_id
        )
    )
    return Decimal(value or 0)


async def get(session: AsyncSession, movement_id: UUID) -> StockMovement | None:
    return await session.get(StockMovement, movement_id)


async def is_reversed(session: AsyncSession, movement_id: UUID) -> bool:
    """Si ya tiene su anulación. Es la comprobación previa del 409; la última
    palabra es el índice único de `reverses_id`."""
    found = await session.scalar(
        select(StockMovement.id).where(StockMovement.reverses_id == movement_id)
    )
    return found is not None


@dataclass(frozen=True)
class HistoryRow:
    movement: StockMovement
    employee_name: str
    # La anulación que lo deshizo, si la tiene.
    reversed_by_id: UUID | None


async def history(
    session: AsyncSession, part_id: UUID, *, before_seq: int | None, limit: int
) -> list[HistoryRow]:
    """Los movimientos de una pieza, del más reciente al más antiguo (RF-96),
    paginados por `seq`, nunca por fecha."""
    reversal = aliased(StockMovement)
    query = (
        select(StockMovement, Employee.name, reversal.id)
        .join(Employee, Employee.id == StockMovement.employee_id)
        .outerjoin(reversal, reversal.reverses_id == StockMovement.id)
        .where(StockMovement.part_id == part_id)
        .order_by(StockMovement.seq.desc())
        .limit(limit)
    )
    if before_seq is not None:
        query = query.where(StockMovement.seq < before_seq)
    rows = await session.execute(query)
    return [
        HistoryRow(movement, name, reversed_by) for movement, name, reversed_by in rows
    ]
