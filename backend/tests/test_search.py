"""La búsqueda única del mostrador (RF-14, RNF-01, RNF-51)."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql

from app.api.deps import get_email_sender
from app.infra.email import InMemoryEmailSender
from app.main import app
from app.scripts.reset_data import truncate_all
from tests.conftest import Engines
from tests.test_clients import create as create_client
from tests.test_clients import open_workshop
from tests.test_employees import AdminSession, add_mechanic, invite_and_accept
from tests.test_vehicles import create as create_vehicle

URL = "/api/v1/workshop/search"


@pytest_asyncio.fixture
async def outbox() -> AsyncIterator[InMemoryEmailSender]:
    sender = InMemoryEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    yield sender
    app.dependency_overrides.pop(get_email_sender, None)


@pytest_asyncio.fixture
async def admin(client: AsyncClient) -> AdminSession:
    """Talleres Pérez con María García (y su Seat), Mario y una empresa."""
    await truncate_all()
    admin = await open_workshop(client, "Talleres Pérez")
    maria = await create_client(
        client, admin.headers, name="María García", phone="600 111 222"
    )
    await create_client(client, admin.headers, name="Mario Ruiz", phone="611 222 333")
    await create_client(
        client,
        admin.headers,
        kind="company",
        name="Transportes Martínez SL",
        phone="910",
    )
    await create_vehicle(
        client, admin.headers, maria["id"], plate="1234 BCD", make="Seat"
    )
    await create_vehicle(client, admin.headers, maria["id"], plate="9999-ZZZ")
    return admin


async def search(client: AsyncClient, headers: dict[str, str], q: str) -> Any:
    response = await client.get(URL, params={"q": q}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def plates(result: Any) -> list[str]:
    return [v["plate"] for v in result["vehicles"]]


def names(result: Any) -> list[str]:
    return [c["name"] for c in result["clients"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["1234BCD", "1234 bcd", "1234-bcd", "34B", "bcd"])
async def test_a_plate_is_found_however_it_is_written(
    client: AsyncClient, admin: AdminSession, q: str
) -> None:
    result = await search(client, admin.headers, q)
    assert plates(result) == ["1234 BCD"]
    [vehicle] = result["vehicles"]
    # Con su titular: el cliente de la orden que se abra.
    assert vehicle["owner"]["name"] == "María García"


@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["maria", "MARÍA", "garcia", "Garcí"])
async def test_a_name_is_found_without_accents_or_case(
    client: AsyncClient, admin: AdminSession, q: str
) -> None:
    result = await search(client, admin.headers, q)
    assert names(result) == ["María García"]


@pytest.mark.asyncio
async def test_a_client_comes_with_their_current_vehicles(
    client: AsyncClient, admin: AdminSession
) -> None:
    [maria] = (await search(client, admin.headers, "maría garcía"))["clients"]
    assert [v["plate"] for v in maria["vehicles"]] == ["1234 BCD", "9999-ZZZ"]
    assert maria["archived"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["600111222", "600 111", "111-222", "1112"])
async def test_a_phone_is_found_by_its_digits(
    client: AsyncClient, admin: AdminSession, q: str
) -> None:
    assert names(await search(client, admin.headers, q)) == ["María García"]


@pytest.mark.asyncio
async def test_one_box_finds_names_that_start_with_it_first(
    client: AsyncClient, admin: AdminSession
) -> None:
    """ "mar" está dentro de "Martínez" y al principio de "María" y "Mario"."""
    assert names(await search(client, admin.headers, "mar")) == [
        "María García",
        "Mario Ruiz",
        "Transportes Martínez SL",
    ]


@pytest.mark.asyncio
async def test_archived_clients_are_found_but_last(
    client: AsyncClient, admin: AdminSession
) -> None:
    """Un cliente que vuelve años después es el mismo: se encuentra, aunque
    detrás de los activos."""
    [maria] = (await search(client, admin.headers, "maría"))["clients"]
    listed = await client.get(
        f"/api/v1/workshop/clients/{maria['id']}", headers=admin.headers
    )
    await client.post(
        f"/api/v1/workshop/clients/{maria['id']}/archive",
        json={"version": listed.json()["version"]},
        headers=admin.headers,
    )
    result = await search(client, admin.headers, "mar")
    assert names(result) == ["Mario Ruiz", "Transportes Martínez SL", "María García"]
    assert result["clients"][-1]["archived"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["", " ", "a", "%", "_", "%%", "\\"])
async def test_too_short_or_wildcards_find_nothing(
    client: AsyncClient, admin: AdminSession, q: str
) -> None:
    """Lo que no sirve para buscar no devuelve todo: ni una letra, ni los
    comodines de LIKE, que se buscan como texto."""
    assert await search(client, admin.headers, q) == {"vehicles": [], "clients": []}


@pytest.mark.asyncio
async def test_the_mechanic_searches_too(
    client: AsyncClient, admin: AdminSession, outbox: InMemoryEmailSender
) -> None:
    mechanic = await invite_and_accept(
        client, admin, outbox, await add_mechanic(client, admin)
    )
    assert plates(await search(client, mechanic, "1234")) == ["1234 BCD"]


@pytest.mark.asyncio
async def test_another_workshop_finds_nothing_of_this_one(
    client: AsyncClient, admin: AdminSession
) -> None:
    """RNF-01: la misma búsqueda desde el taller B no ve nada del A, y viceversa."""
    b = (await open_workshop(client, "Taller B")).headers
    ana_b = await create_client(client, b, name="María de B", phone="600 111 999")
    await create_vehicle(client, b, ana_b["id"], plate="1234 XYZ")

    from_b = await search(client, b, "1234")
    assert plates(from_b) == ["1234 XYZ"]
    assert names(await search(client, b, "maria")) == ["María de B"]
    assert names(await search(client, b, "600111")) == ["María de B"]
    assert plates(await search(client, admin.headers, "1234")) == ["1234 BCD"]


@pytest_asyncio.fixture
async def busy_neighbour(engines: Engines, admin: AdminSession) -> str:
    """Otro taller en la misma instalación, con 5.000 clientes y 5.000
    vehículos, y estadísticas al día. El de Ana tiene unas pocas filas."""
    async with engines.platform.begin() as conn:
        other = await conn.scalar(
            text("INSERT INTO workshops (name) VALUES ('Vecino') RETURNING id")
        )
        await conn.execute(
            text(
                "INSERT INTO clients (workshop_id, name, phone)"
                " SELECT :w, 'María ' || n, (600000000 + n)::text"
                " FROM generate_series(1, 5000) AS n"
            ),
            {"w": other},
        )
        await conn.execute(
            text(
                "INSERT INTO vehicles (workshop_id, plate, plate_normalized)"
                " SELECT :w, n || 'BCD', n || 'BCD'"
                " FROM generate_series(1, 5000) AS n"
            ),
            {"w": other},
        )
    # ANALYZE solo lo puede hacer el dueño de las tablas.
    async with engines.owner.connect() as conn:
        await conn.execute(text("ANALYZE clients"))
        await conn.execute(text("ANALYZE vehicles"))
        await conn.commit()
    return admin.invited.workshop_id


@pytest.mark.asyncio
@pytest.mark.parametrize("build", ["name", "phone", "plate"])
async def test_the_search_never_walks_through_other_workshops(
    busy_neighbour: str, build: str
) -> None:
    """RNF-51 en una instalación de muchos talleres. El "contiene" recorre las
    filas del taller (bajo RLS no puede usar un índice, ver la prueba
    siguiente), pero solo las suyas: el índice por workshop_id lo lleva a ellas
    sin pasar por las 5.000 del vecino. Es la igualdad de la política de RLS,
    que sí es LEAKPROOF."""
    from app.core import db
    from app.models import Client, Vehicle
    from app.repositories.search import contains_text, escape_like

    queries = {
        "name": select(Client.id).where(contains_text(Client.name_search, "maría")),
        "phone": select(Client.id).where(
            Client.phone_digits.like(f"%{escape_like('111222')}%")
        ),
        "plate": select(Vehicle.id).where(
            Vehicle.plate_normalized.like(f"%{escape_like('34BC')}%")
        ),
    }
    statement = queries[build].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    # literal_binds duplica los % para el estilo de parámetros del driver.
    sql = str(statement).replace("%%", "%")
    try:
        async with db.workshop_transaction([UUID(busy_neighbour)]) as session:
            plan = "\n".join((await session.scalars(text(f"EXPLAIN {sql}"))).all())
    finally:
        await db.engine.dispose()
    assert "Seq Scan" not in plan, plan
    assert "Index Cond: (workshop_id = ANY" in plan, plan


@pytest.mark.asyncio
async def test_like_is_not_leakproof_so_rls_cannot_index_it(engines: Engines) -> None:
    """Por qué no hay índices trigram (migración 0008search): Postgres solo usa
    un índice para una condición bajo RLS si su operador es LEAKPROOF, y LIKE
    no lo es. Si una versión futura de Postgres lo cambiara, esta prueba avisa
    de que los índices volverían a servir."""
    async with engines.platform.connect() as conn:
        leakproof: dict[str, bool] = dict(
            (
                await conn.execute(
                    text(
                        "SELECT proname, proleakproof FROM pg_proc"
                        " WHERE proname IN ('textlike', 'uuid_eq')"
                    )
                )
            ).all()
        )
    assert leakproof == {"textlike": False, "uuid_eq": True}
