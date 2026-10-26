from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client


async def get(session: AsyncSession, client_id: UUID) -> Client | None:
    """Bajo RLS: un cliente de otro taller no existe (None, y por tanto 404)."""
    return await session.get(Client, client_id)


async def email_taken(
    session: AsyncSession, email: str, *, except_id: UUID | None = None
) -> bool:
    query = select(Client.id).where(Client.email == email)
    if except_id is not None:
        query = query.where(Client.id != except_id)
    return (await session.scalar(query.limit(1))) is not None


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


async def list_page(
    session: AsyncSession,
    *,
    query: str | None,
    archived: bool,
    limit: int,
    offset: int,
) -> list[Client]:
    """Clientes del taller fijado, por nombre.

    El filtro por texto es el sencillo de esta pantalla. La búsqueda única del
    mostrador (RF-14, con matrícula e índices propios) llega en el paso 6 de F2.
    """
    statement = select(Client).where(
        Client.archived_at.is_not(None) if archived else Client.archived_at.is_(None)
    )
    if query:
        pattern = f"%{_escape_like(query)}%"
        statement = statement.where(
            or_(
                Client.name.ilike(pattern),
                Client.phone.ilike(pattern),
                Client.email.ilike(pattern),
                Client.tax_id.ilike(pattern),
            )
        )
    rows = await session.scalars(
        statement.order_by(Client.name, Client.id).limit(limit).offset(offset)
    )
    return list(rows)
