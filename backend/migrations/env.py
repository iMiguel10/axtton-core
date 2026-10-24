import asyncio
import os

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# Las migraciones se conectan SIEMPRE como dueño de las tablas (axtton_owner),
# nunca con el rol de la aplicación: axtton_app no puede crear tablas ni políticas.
# Se lee del entorno (y no de Settings) para que las pruebas puedan apuntar a la
# base de pruebas sin tocar la configuración de la API.
URL = os.environ["MIGRATIONS_DATABASE_URL"]

# Sin target_metadata: las migraciones de F0 se escriben a mano, porque
# --autogenerate no sabe de RLS, políticas ni triggers.
target_metadata = None


def run_migrations_offline() -> None:
    context.configure(url=URL, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(URL)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
