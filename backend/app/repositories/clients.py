from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client
from app.repositories.search import contains_text


async def get(session: AsyncSession, client_id: UUID) -> Client | None:
    """Bajo RLS: un cliente de otro taller no existe (None, y por tanto 404)."""
    return await session.get(Client, client_id)


async def get_locked(
    session: AsyncSession, client_id: UUID, *, shared: bool
) -> Client | None:
    """El cliente, bloqueado hasta el final de la transacción.

    Anonimizar pide el bloqueo exclusivo (`shared=False`); abrir una orden o
    darle un vehículo, el compartido. Así, quien llega segundo espera y ve lo
    que hizo el primero: nunca se abre una orden para un cliente que se está
    anonimizando, ni se anonimiza uno al que se le está abriendo una. El
    bloqueo que pone la FK de la orden al insertarla no basta: también espera,
    pero llega tarde, con el cliente ya leído sin anonimizar (como con el
    titular del vehículo, test_concurrency.py).
    """
    query = (
        select(Client)
        .where(Client.id == client_id)
        .with_for_update(read=shared)
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(query)).one_or_none()


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

    El filtro por texto es el de esta pantalla (también por email y NIF). La
    búsqueda única del mostrador, con matrícula, está en repositories/search.py.
    """
    statement = select(Client).where(
        Client.archived_at.is_not(None) if archived else Client.archived_at.is_(None)
    )
    if query:
        pattern = f"%{_escape_like(query)}%"
        statement = statement.where(
            or_(
                # Sin tildes ni mayúsculas, como la búsqueda del mostrador.
                contains_text(Client.name_search, query),
                Client.phone.ilike(pattern),
                Client.email.ilike(pattern),
                Client.tax_id.ilike(pattern),
            )
        )
    rows = await session.scalars(
        statement.order_by(Client.name, Client.id).limit(limit).offset(offset)
    )
    return list(rows)
