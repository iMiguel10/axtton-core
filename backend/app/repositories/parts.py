"""El catálogo de piezas del taller fijado (F7, RF-90), siempre bajo RLS: una
pieza de otro taller no existe.

El stock de cada pieza se lee aquí como la suma de sus movimientos
(invariante 9), con una subconsulta por pieza que sirve el índice
`ix_stock_movements_workshop_id_part_id` sin tocar la tabla.
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Part, StockMovement
from app.repositories.search import contains_text


def stock_expression() -> ColumnElement[Decimal]:
    """La suma de los movimientos de la pieza de la fila; 0 si no tiene."""
    return (
        select(func.coalesce(func.sum(StockMovement.quantity), 0))
        .where(StockMovement.part_id == Part.id)
        .correlate(Part)
        .scalar_subquery()
    )


async def get(session: AsyncSession, part_id: UUID) -> Part | None:
    return await session.get(Part, part_id)


async def get_with_stock(
    session: AsyncSession, part_id: UUID
) -> tuple[Part, Decimal] | None:
    row = (
        await session.execute(
            select(Part, stock_expression()).where(Part.id == part_id)
        )
    ).one_or_none()
    return (row[0], row[1]) if row else None


async def reference_taken(
    session: AsyncSession, reference: str, *, except_id: UUID | None = None
) -> bool:
    """Si otra pieza del taller ya tiene esa referencia, archivada o no. Es la
    comprobación previa del 409; la última palabra es el índice único."""
    query = select(Part.id).where(func.lower(Part.reference) == reference.lower())
    if except_id is not None:
        query = query.where(Part.id != except_id)
    return (await session.scalar(query.limit(1))) is not None


async def list_page(
    session: AsyncSession,
    *,
    query: str | None,
    archived: bool,
    alert: bool,
    limit: int,
    offset: int,
) -> list[tuple[Part, Decimal]]:
    """Las piezas del taller con su stock, por descripción. El texto busca a la
    vez en la referencia, la marca y la descripción, sin tildes ni mayúsculas.
    Con `alert`, solo las que se cuentan y están en negativo o por debajo de su
    mínimo (RF-94, RF-95)."""
    stock = stock_expression()
    statement = select(Part, stock).where(
        Part.archived_at.is_not(None) if archived else Part.archived_at.is_(None)
    )
    if query:
        statement = statement.where(contains_text(Part.search, query))
    if alert:
        statement = statement.where(
            Part.tracks_stock,
            or_(
                stock < 0,
                and_(Part.min_stock.is_not(None), stock < Part.min_stock),
            ),
        )
    rows = await session.execute(
        statement.order_by(Part.description, Part.reference, Part.id)
        .limit(limit)
        .offset(offset)
    )
    return [(part, part_stock) for part, part_stock in rows]
