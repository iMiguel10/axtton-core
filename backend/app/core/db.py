from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

# Un único engine por proceso, con el rol axtton_app: mantiene el pool de
# conexiones a Postgres.
engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)

# expire_on_commit=False: tras el commit, los objetos siguen legibles sin otra
# consulta. Con async es casi obligatorio, porque una recarga implícita fuera de
# un `await` falla.
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Sesión sin taller fijado: bajo RLS no ve ninguna fila de taller.

    Sirve para lo que no toca datos de taller (como /api/health).
    """
    async with SessionFactory() as session:
        yield session


def _as_pg_array(workshop_ids: Sequence[UUID]) -> str:
    return "{" + ",".join(str(workshop_id) for workshop_id in workshop_ids) + "}"


async def set_workshops(session: AsyncSession, workshop_ids: Sequence[UUID]) -> None:
    """Fija los talleres visibles para RLS **solo en la transacción en curso**.

    El tercer argumento de set_config, `true`, es lo que lo limita a la
    transacción. Con `false` el valor se quedaría pegado a la conexión, y la
    siguiente petición que la reutilizara desde el pool vería el taller anterior
    (prueba R7).
    """
    await session.execute(
        text("SELECT set_config('app.workshop_ids', :ids, true)"),
        {"ids": _as_pg_array(workshop_ids)},
    )


@asynccontextmanager
async def workshop_transaction(
    workshop_ids: Sequence[UUID],
) -> AsyncIterator[AsyncSession]:
    """Abre una transacción con los talleres ya fijados para RLS.

    Al salir del bloque se hace commit, o rollback si hubo una excepción.
    """
    async with SessionFactory() as session, session.begin():
        await set_workshops(session, workshop_ids)
        yield session
