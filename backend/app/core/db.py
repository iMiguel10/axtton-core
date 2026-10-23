from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

# Un único engine por proceso: mantiene el pool de conexiones a Postgres.
engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)

# expire_on_commit=False: tras el commit, los objetos siguen legibles sin otra
# consulta. Con async es casi obligatorio, porque una recarga implícita fuera de
# un `await` falla.
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependencia de FastAPI: una sesión por petición, cerrada al terminar."""
    async with SessionFactory() as session:
        yield session
