"""Las pruebas corren contra la base axtton_test, con los roles reales y RLS activa.

Nunca SQLite ni una base "de mentira": RLS, las FK compuestas y los permisos
de cada rol no existirían, y las pruebas pasarían en verde sin probar nada.
"""

import os
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID, uuid4

# Antes de importar nada de la aplicación: Settings lee estas variables al crear
# el engine, y tienen que apuntar a la base de pruebas, no a la de desarrollo.
TEST_DB = os.environ.get("POSTGRES_TEST_DB", "axtton_test")
for _var in ("DATABASE_URL", "PLATFORM_DATABASE_URL", "MIGRATIONS_DATABASE_URL"):
    os.environ[_var] = os.environ[_var].rpartition("/")[0] + f"/{TEST_DB}"
# Sin límite de peticiones: las pruebas inician sesión muchas veces seguidas desde
# la misma "IP". Las que prueban el límite ponen el suyo (test_rate_limit.py).
os.environ["RATE_LIMIT_ENABLED"] = "false"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import app.main  # noqa: F401
from app.scripts.reset_data import truncate_all

# app.main se importa AQUÍ, una vez, antes de cualquier fixture: al importarse
# inicializa SuperTokens y fija el emisor de correo del proceso. Si se importara
# por primera vez dentro de un fixture, pisaría el emisor de pruebas que otro
# fixture acabara de poner (le pasó a test_account.py).


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
class Account:
    email: str
    password: str
    supertokens_user_id: str


@pytest_asyncio.fixture
async def make_account(
    engines: Engines,
) -> Callable[[str], Awaitable[Account]]:
    """Crea cuentas como lo hará la aplicación: usuario en SuperTokens y fila en users.

    La base de datos de SuperTokens no se vacía entre pruebas, así que cada email
    es único.
    """
    from supertokens_python.recipe.emailpassword.asyncio import sign_up
    from supertokens_python.recipe.emailpassword.interfaces import SignUpOkResult

    async def create(kind: str) -> Account:
        email = f"{kind}-{uuid4().hex[:12]}@example.com"
        password = "una-contraseña-larga-1"
        result = await sign_up("public", email, password)
        assert isinstance(result, SignUpOkResult)
        if kind != "orphan":
            async with engines.platform.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO users (supertokens_user_id, kind) VALUES (:s, :k)"
                    ),
                    {"s": result.user.id, "k": kind},
                )
        return Account(email, password, result.user.id)

    return create


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Cliente HTTP contra la app en memoria (sin red), con el middleware de SuperTokens."""
    from app.core import db
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http
    # Los engines de la aplicación y de plataforma son globales: sus conexiones
    # quedan ligadas al event loop de esta prueba, y la siguiente usa otro
    # ("Event loop is closed"). Se cierran aquí, los dos.
    from app.platform.db import platform_engine

    await db.engine.dispose()
    await platform_engine.dispose()


async def sign_in(client: AsyncClient, account: Account) -> str:
    """Inicia sesión en modo cabecera y devuelve el access token (Bearer)."""
    response = await client.post(
        "/api/auth/signin",
        headers={"st-auth-mode": "header"},
        json={
            "formFields": [
                {"id": "email", "value": account.email},
                {"id": "password", "value": account.password},
            ]
        },
    )
    assert response.json()["status"] == "OK", response.text
    return response.headers["st-access-token"]


@dataclass(frozen=True)
class TwoWorkshops:
    a: UUID
    b: UUID
    admin_a: UUID
    admin_b: UUID


@pytest_asyncio.fixture
async def two_workshops(engines: Engines) -> TwoWorkshops:
    """Dos talleres con un empleado administrador cada uno.

    Se crean con la conexión de plataforma: es la única que puede escribir en
    los dos a la vez.
    """
    await truncate_all()
    workshops, admins = [], []
    async with engines.platform.begin() as conn:
        for name in ("A", "B"):
            workshop_id = await conn.scalar(
                text("INSERT INTO workshops (name) VALUES (:n) RETURNING id"),
                {"n": f"Taller {name}"},
            )
            employee_id = await conn.scalar(
                text(
                    "INSERT INTO employees (workshop_id, name, role)"
                    " VALUES (:w, :n, 'admin') RETURNING id"
                ),
                {"w": workshop_id, "n": f"Admin {name}"},
            )
            workshops.append(workshop_id)
            admins.append(employee_id)
    return TwoWorkshops(
        a=workshops[0], b=workshops[1], admin_a=admins[0], admin_b=admins[1]
    )
