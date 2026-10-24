"""Las pruebas corren contra la base axtton_test, con los roles reales y RLS activa.

Nunca SQLite ni una base "de mentira": RLS, las FK compuestas y los permisos
de cada rol no existirían, y las pruebas pasarían en verde sin probar nada.
"""

import os
import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

# Antes de importar nada de la aplicación: Settings lee estas variables al crear
# el engine, y tienen que apuntar a la base de pruebas, no a la de desarrollo.
TEST_DB = os.environ.get("POSTGRES_TEST_DB", "axtton_test")
for _var in ("DATABASE_URL", "PLATFORM_DATABASE_URL", "MIGRATIONS_DATABASE_URL"):
    os.environ[_var] = os.environ[_var].rpartition("/")[0] + f"/{TEST_DB}"

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Aplica las migraciones a la base de pruebas una vez por sesión."""
    subprocess.run(["alembic", "upgrade", "head"], check=True)


@dataclass(frozen=True)
class Engines:
    app: AsyncEngine
    platform: AsyncEngine
    owner: AsyncEngine


@pytest_asyncio.fixture
async def engines() -> AsyncIterator[Engines]:
    """Un engine por rol, creados en el event loop de cada prueba."""
    created = Engines(
        app=create_async_engine(os.environ["DATABASE_URL"]),
        platform=create_async_engine(os.environ["PLATFORM_DATABASE_URL"]),
        owner=create_async_engine(os.environ["MIGRATIONS_DATABASE_URL"]),
    )
    yield created
    for engine in (created.app, created.platform, created.owner):
        await engine.dispose()


@dataclass(frozen=True)
class TwoWorkshops:
    a: UUID
    b: UUID


@pytest_asyncio.fixture
async def two_workshops(engines: Engines) -> TwoWorkshops:
    """Dos talleres con un cliente, un vehículo y una orden cada uno.

    Se crean con la conexión de plataforma: es la única que puede escribir en
    los dos a la vez.
    """
    async with engines.platform.begin() as conn:
        for table in ("work_orders", "vehicles", "clients", "workshops"):
            await conn.execute(text(f"DELETE FROM {table}"))
        ids = []
        for name in ("A", "B"):
            workshop_id = await conn.scalar(
                text("INSERT INTO workshops (name) VALUES (:n) RETURNING id"),
                {"n": f"Taller {name}"},
            )
            client_id = await conn.scalar(
                text(
                    "INSERT INTO clients (workshop_id, name) VALUES (:w, :n) RETURNING id"
                ),
                {"w": workshop_id, "n": f"Cliente {name}"},
            )
            vehicle_id = await conn.scalar(
                text(
                    "INSERT INTO vehicles (workshop_id, plate) VALUES (:w, :p) RETURNING id"
                ),
                {"w": workshop_id, "p": f"0000{name}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO work_orders (workshop_id, vehicle_id, client_id)"
                    " VALUES (:w, :v, :c)"
                ),
                {"w": workshop_id, "v": vehicle_id, "c": client_id},
            )
            ids.append(workshop_id)
    return TwoWorkshops(a=ids[0], b=ids[1])
