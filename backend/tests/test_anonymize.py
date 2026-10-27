"""Anonimizar a un cliente que lo pide (RF-15, RNF-40).

Por la API: qué se vacía, qué se conserva y qué ya no se puede hacer después.
Por la base de datos: que no se pueda deshacer ni dejar a medias. Y un barrido
de todas las tablas buscando lo que el cliente era.
"""

import os
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.infra.email import InMemoryEmailSender
from tests.conftest import Engines, TwoWorkshops
from tests.test_clients import open_workshop
from tests.test_employees import add_mechanic, invite_and_accept
from tests.test_payment import deliver
from tests.test_vehicles import change_owner
from tests.test_vehicles import get as get_vehicle
from tests.test_work_orders import Shop, get, new_shop, open_order, outbox
from tests.test_work_orders_db import Order, seed_order

__all__ = ["outbox"]

CLIENTS = "/api/v1/workshop/clients"

# Lo que María era. Ninguno debe quedar en ninguna tabla después.
PERSONAL = {
    "name": "María Sánchez Ortiz",
    "phone": "699 123 987",
    "email": "maria.sanchez@example.com",
    "tax_id": "12345678Z",
    "address": "Calle del Olmo 7, Albacete",
    "notes": "Prefiere que la llamen por la tarde",
}
DROPPED_OFF = {
    "dropped_off_by_name": "Jaime Sánchez",
    "dropped_off_by_phone": "688 777 666",
}


@pytest_asyncio.fixture
async def shop(client: AsyncClient) -> Shop:
    return await new_shop(client)


async def read(client: AsyncClient, headers: dict[str, str], client_id: str) -> Any:
    response = await client.get(f"{CLIENTS}/{client_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def anonymize(
    client: AsyncClient, headers: dict[str, str], target: dict[str, Any]
) -> Any:
    return await client.post(
        f"{CLIENTS}/{target['id']}/anonymize",
        json={"version": target["version"]},
        headers=headers,
    )


async def maria_with_history(client: AsyncClient, shop: Shop) -> tuple[Any, Any]:
    """María, con todos sus datos, y una orden entregada de su coche traída por
    su hijo."""
    response = await client.patch(
        f"{CLIENTS}/{shop.maria['id']}",
        json={"version": shop.maria["version"], **PERSONAL},
        headers=shop.headers,
    )
    assert response.status_code == 204, response.text
    order = await open_order(client, shop.headers, shop.car["id"], **DROPPED_OFF)
    await deliver(order["id"])
    return await read(client, shop.headers, shop.maria["id"]), order


@pytest.mark.asyncio
async def test_anonymizing_empties_the_client_and_keeps_its_orders(
    client: AsyncClient, shop: Shop
) -> None:
    maria, order = await maria_with_history(client, shop)
    assert (await anonymize(client, shop.headers, maria)).status_code == 204

    after = await read(client, shop.headers, maria["id"])
    assert {k: after[k] for k in PERSONAL} == {
        "name": "",
        "phone": "",
        "email": None,
        "tax_id": None,
        "address": None,
        "notes": None,
    }
    assert after["anonymized_at"] is not None
    assert after["archived_at"] is not None

    # La orden sigue, ligada al mismo cliente, sin quién trajo el coche.
    kept = await get(client, shop.headers, order["id"])
    assert kept["client"] == {"id": maria["id"], "name": "", "phone": ""}
    assert (kept["dropped_off_by_name"], kept["dropped_off_by_phone"]) == (None, None)
    # Y el coche, con su historial de titulares.
    car = await get_vehicle(client, shop.headers, shop.car["id"])
    assert car["owner"]["id"] == maria["id"]

    audit = await client.get("/api/v1/workshop/audit", headers=shop.headers)
    [entry] = [e for e in audit.json()["entries"] if e["action"] == "client_anonymized"]
    assert (entry["target_type"], entry["target_name"], entry["actor"]) == (
        "client",
        "",
        "Ana López",
    )


@pytest.mark.asyncio
async def test_nothing_of_the_client_is_left_in_any_table(
    client: AsyncClient, shop: Shop
) -> None:
    """RNF-40: tras anonimizar, el dato personal no está en ninguna tabla de la
    aplicación, tampoco en el registro de auditoría ni en las columnas de
    búsqueda. Se recorre cada fila de cada tabla convertida en texto, así que
    una tabla o columna nueva que lo guarde hace fallar esta prueba."""
    maria, _ = await maria_with_history(client, shop)
    assert (await anonymize(client, shop.headers, maria)).status_code == 204

    engine = create_async_engine(os.environ["PLATFORM_DATABASE_URL"])
    try:
        async with engine.connect() as conn:
            tables = (
                await conn.scalars(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                        # alembic_version no es de nadie más que del dueño.
                        " AND has_table_privilege("
                        "quote_ident(schemaname) || '.' || quote_ident(tablename), 'SELECT')"
                    )
                )
            ).all()
            dump = "\n".join(
                [
                    row
                    for table in tables
                    for row in (
                        await conn.scalars(text(f'SELECT t::text FROM "{table}" t'))
                    ).all()
                ]
            ).lower()
    finally:
        await engine.dispose()
    searched = [
        *PERSONAL.values(),
        *DROPPED_OFF.values(),
        "maria sanchez",  # name_search, sin tildes
        "699123987",  # phone_digits
    ]
    assert [value for value in searched if value.lower() in dump] == []


@pytest.mark.asyncio
async def test_a_client_with_an_open_order_cannot_be_anonymized(
    client: AsyncClient, shop: Shop
) -> None:
    """Esa orden aún necesita a quién avisar. Primero se entrega o se cancela."""
    await open_order(client, shop.headers, shop.car["id"])
    maria = await read(client, shop.headers, shop.maria["id"])
    response = await anonymize(client, shop.headers, maria)
    assert (response.status_code, response.json()) == (
        409,
        {"code": "client_has_open_orders"},
    )
    assert (await read(client, shop.headers, maria["id"]))["name"] == "María"


@pytest.mark.asyncio
async def test_an_anonymized_client_stays_anonymized(
    client: AsyncClient, shop: Shop
) -> None:
    """Irreversible (RF-15): ni se edita, ni se desarchiva, ni se vuelve a
    anonimizar."""
    maria = await read(client, shop.headers, shop.maria["id"])
    await anonymize(client, shop.headers, maria)
    after = await read(client, shop.headers, maria["id"])
    version = {"version": after["version"]}
    for response in (
        await anonymize(client, shop.headers, after),
        await client.patch(
            f"{CLIENTS}/{after['id']}",
            json={**version, "name": "María"},
            headers=shop.headers,
        ),
        await client.post(
            f"{CLIENTS}/{after['id']}/unarchive", json=version, headers=shop.headers
        ),
    ):
        assert (response.status_code, response.json()) == (
            409,
            {"code": "client_anonymized"},
        )


@pytest.mark.asyncio
async def test_its_vehicle_needs_a_new_owner_before_a_new_order(
    client: AsyncClient, shop: Shop
) -> None:
    """El coche sigue siendo "del cliente eliminado" en su historial. Quien lo
    trae ahora es otro titular: se cambia antes de abrirle una orden, y nadie
    recibe un vehículo a nombre de un anonimizado."""
    maria = await read(client, shop.headers, shop.maria["id"])
    await anonymize(client, shop.headers, maria)

    refused = await client.post(
        "/api/v1/workshop/orders",
        json={"vehicle_id": shop.car["id"], "type": "breakdown"},
        headers=shop.headers,
    )
    assert (refused.status_code, refused.json()) == (409, {"code": "client_anonymized"})

    luis_car = await client.post(
        "/api/v1/workshop/vehicles",
        json={"plate": "9999 KKK", "owner_id": shop.luis["id"]},
        headers=shop.headers,
    )
    assert luis_car.status_code == 201, luis_car.text
    luis_vehicle = await get_vehicle(client, shop.headers, luis_car.json()["id"])
    to_anonymized = await change_owner(client, shop.headers, luis_vehicle, maria["id"])
    assert (to_anonymized.status_code, to_anonymized.json()) == (
        409,
        {"code": "client_anonymized"},
    )

    car = await get_vehicle(client, shop.headers, shop.car["id"])
    assert (
        await change_owner(client, shop.headers, car, shop.luis["id"])
    ).status_code == 204
    await open_order(client, shop.headers, shop.car["id"])


@pytest.mark.asyncio
async def test_the_search_no_longer_finds_the_client(
    client: AsyncClient, shop: Shop
) -> None:
    maria, _ = await maria_with_history(client, shop)
    await anonymize(client, shop.headers, maria)
    for q in ("maria", "699123987"):
        found = await client.get(
            "/api/v1/workshop/search", params={"q": q}, headers=shop.headers
        )
        assert found.json()["clients"] == [], q


@pytest.mark.asyncio
async def test_only_an_admin_anonymizes_and_with_the_current_version(
    client: AsyncClient, shop: Shop, outbox: InMemoryEmailSender
) -> None:
    mechanic = await invite_and_accept(
        client, shop.admin, outbox, await add_mechanic(client, shop.admin)
    )
    maria = await read(client, shop.headers, shop.maria["id"])
    forbidden = await anonymize(client, mechanic, maria)
    assert (forbidden.status_code, forbidden.json()) == (403, {"code": "not_allowed"})

    stale = await anonymize(
        client, shop.headers, {**maria, "version": maria["version"] - 1}
    )
    assert (stale.status_code, stale.json()) == (
        409,
        {"code": "modified_by_someone_else"},
    )

    other = (await open_workshop(client, "Talleres Gómez")).headers
    foreign = await anonymize(client, other, maria)
    assert (foreign.status_code, foreign.json()) == (404, {"code": "client_not_found"})
    assert (await read(client, shop.headers, maria["id"]))["anonymized_at"] is None


# --- Lo que garantiza la base de datos ---------------------------------------


@pytest_asyncio.fixture
async def order(engines: Engines, two_workshops: TwoWorkshops) -> Order:
    """Trae una clienta, María, en el taller A."""
    return await seed_order(engines, two_workshops)


ANONYMIZE_SQL = (
    "UPDATE clients SET name = '', phone = '', anonymized_at = clock_timestamp(),"
    " archived_at = clock_timestamp() WHERE workshop_id = :w"
)


@pytest.mark.asyncio
async def test_the_database_refuses_a_half_anonymized_client(
    engines: Engines, order: Order
) -> None:
    """Con `anonymized_at` y aún con nombre, teléfono o sin archivar: no."""
    for statement in (
        "UPDATE clients SET anonymized_at = clock_timestamp(), archived_at = now()",
        (
            "UPDATE clients SET name = '', anonymized_at = clock_timestamp(),"
            " archived_at = now()"
        ),
        "UPDATE clients SET name = '', phone = '', anonymized_at = clock_timestamp()",
    ):
        with pytest.raises(IntegrityError, match="ck_clients_anonymized_empty"):
            async with engines.platform.begin() as conn:
                await conn.execute(
                    text(f"{statement} WHERE workshop_id = :w"),
                    {"w": order.workshop_id},
                )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE clients SET name = 'María', phone = '600', anonymized_at = NULL",
        "UPDATE clients SET archived_at = NULL, anonymized_at = NULL",
        "UPDATE clients SET language = 'en'",
    ],
)
async def test_nobody_undoes_an_anonymization(
    engines: Engines, order: Order, statement: str
) -> None:
    """Ni la plataforma, que se salta RLS: lo para el trigger."""
    async with engines.platform.begin() as conn:
        await conn.execute(text(ANONYMIZE_SQL), {"w": order.workshop_id})
    with pytest.raises(DBAPIError, match="an anonymized client cannot be changed"):
        async with engines.platform.begin() as conn:
            await conn.execute(
                text(f"{statement} WHERE workshop_id = :w"), {"w": order.workshop_id}
            )
