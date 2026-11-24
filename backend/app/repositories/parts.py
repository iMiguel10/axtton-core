"""El catálogo de piezas del taller fijado (F7, RF-90), siempre bajo RLS: una
pieza de otro taller no existe."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Part
from app.repositories.search import contains_text


async def get(session: AsyncSession, part_id: UUID) -> Part | None:
    return await session.get(Part, part_id)


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
    limit: int,
    offset: int,
) -> list[Part]:
    """Las piezas del taller, por descripción. El texto busca a la vez en la
    referencia, la marca y la descripción, sin tildes ni mayúsculas."""
    statement = select(Part).where(
        Part.archived_at.is_not(None) if archived else Part.archived_at.is_(None)
    )
    if query:
        statement = statement.where(contains_text(Part.search, query))
    rows = await session.scalars(
        statement.order_by(Part.description, Part.reference, Part.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows)
