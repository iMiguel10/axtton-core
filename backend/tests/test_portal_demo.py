"""Entrar en el portal de la demo sin correo (F4 paso 8).

La demo desplegada no tiene SMTP, así que un visitante no recibiría nunca el
enlace. Con `DEMO_PORTAL_ENTRY`, la entrada de un taller ofrece sus clientes del
dominio de la demo, y entrar como uno emite un enlace de verdad y lo consume en el
acto: la sesión nace por el mismo camino (T10). Apagada, las dos rutas no existen,
y nunca sirven para un cliente de verdad.
"""

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text

from app.core.config import get_settings
from app.domain.portal import DEMO_CLIENT_DOMAIN, DEMO_CLIENTS_SHOWN
from tests.conftest import Engines
from tests.test_clients import open_workshop
from tests.test_portal_auth import bearer, claims
from tests.test_portal_orders import email_client, workshop_id_of
from tests.test_work_orders import Shop, new_shop, open_order

PORTAL = "/api/v1/portal"


@pytest.fixture
def demo_entry() -> Iterator[None]:
    settings = get_settings()
    previous = settings.demo_portal_entry
    settings.demo_portal_entry = True
    yield
    settings.demo_portal_entry = previous


def demo_email(name: str) -> str:
    return f"{name}-{uuid4().hex[:6]}{DEMO_CLIENT_DOMAIN}"


async def listed(client: AsyncClient, workshop_id: UUID | str) -> Response:
    return await client.get(f"{PORTAL}/workshops/{workshop_id}/demo-clients")


async def enter(client: AsyncClient, workshop_id: UUID | str, email: str) -> Response:
    return await client.post(
        f"{PORTAL}/auth/demo-enter",
        headers={"st-auth-mode": "header"},
        json={"workshop_id": str(workshop_id), "email": email},
    )


async def links(engines: Engines) -> list[tuple[bool]]:
    async with engines.platform.connect() as conn:
        rows = await conn.execute(text("SELECT used_at IS NOT NULL FROM portal_links"))
        return [tuple(row) for row in rows]


# --- Apagada: no existe ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_without_the_setting_neither_route_exists(
    client: AsyncClient, engines: Engines
) -> None:
    """Una instalación de verdad: ni la lista ni la entrada, aunque el cliente sea
    del dominio de la demo."""
    assert get_settings().demo_portal_entry is False
    shop = await new_shop(client)
    email = await email_client(client, shop, shop.maria, demo_email("maria"))
    workshop_id = workshop_id_of(shop)

    for response in (
        await listed(client, workshop_id),
        await enter(client, workshop_id, email),
    ):
        assert (response.status_code, response.json()["code"]) == (404, "not_found")
    assert "st-access-token" not in (await enter(client, workshop_id, email)).headers
    assert await links(engines) == []


# --- Encendida ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_entry_offers_only_the_demo_clients_of_that_workshop(
    client: AsyncClient, demo_entry: None
) -> None:
    shop = await new_shop(client)
    workshop_id = workshop_id_of(shop)
    await email_client(client, shop, shop.maria, demo_email("maria"))
    # Luis tiene un email de verdad: nunca se ofrece.
    await email_client(client, shop, shop.luis, "luis@example.com")

    response = await listed(client, workshop_id)
    assert response.status_code == 200, response.text
    assert [c["name"] for c in response.json()] == ["María"]
    assert response.json()[0]["email"].endswith(DEMO_CLIENT_DOMAIN)

    # Los de otro taller no salen en este.
    other = await open_workshop(client, "Taller B")
    assert (await listed(client, other.invited.workshop_id)).json() == []


@pytest.mark.asyncio
async def test_at_most_a_few_are_offered(client: AsyncClient, demo_entry: None) -> None:
    shop = await new_shop(client)
    for i in range(DEMO_CLIENTS_SHOWN + 2):
        response = await client.post(
            "/api/v1/workshop/clients",
            json={
                "name": f"Cliente {i}",
                "phone": f"60000000{i}",
                "email": demo_email(f"c{i}"),
            },
            headers=shop.headers,
        )
        assert response.status_code == 201, response.text
    offered = (await listed(client, workshop_id_of(shop))).json()
    assert len(offered) == DEMO_CLIENTS_SHOWN


@pytest.mark.asyncio
async def test_entering_as_a_demo_client_consumes_a_real_link(
    client: AsyncClient, engines: Engines, demo_entry: None
) -> None:
    """Lo mismo que abrir el enlace del correo: un enlace guardado y ya usado, y una
    sesión del cliente de ese taller que ve sus órdenes."""
    shop = await new_shop(client)
    workshop_id = workshop_id_of(shop)
    email = await email_client(client, shop, shop.maria, demo_email("maria"))
    order = await open_order(client, shop.headers, shop.car["id"])

    response = await enter(client, workshop_id, email.upper())
    assert response.status_code == 204, response.text
    assert await links(engines) == [(True,)]
    token = claims(response)
    assert (token["actor"], token["workshop_id"], token["client_id"]) == (
        "client",
        str(workshop_id),
        shop.maria["id"],
    )
    vehicles = await client.get(f"{PORTAL}/vehicles", headers=bearer(response))
    assert vehicles.status_code == 200
    assert [o["id"] for v in vehicles.json() for o in v["orders"]] == [order["id"]]


@pytest.mark.asyncio
async def test_a_real_client_is_never_entered_without_mail(
    client: AsyncClient, engines: Engines, demo_entry: None
) -> None:
    """Aunque la variable estuviera encendida por error: solo el dominio de la demo."""
    shop = await new_shop(client)
    email = await email_client(client, shop, shop.luis, "luis@example.com")
    response = await enter(client, workshop_id_of(shop), email)
    assert (response.status_code, response.json()["code"]) == (
        404,
        "demo_client_not_found",
    )
    assert "st-access-token" not in response.headers
    assert await links(engines) == []


@pytest.mark.asyncio
async def test_a_demo_client_of_another_workshop_or_without_access_is_not_found(
    client: AsyncClient, engines: Engines, demo_entry: None
) -> None:
    shop = await new_shop(client)
    email = await email_client(client, shop, shop.maria, demo_email("maria"))
    other = await open_workshop(client, "Taller B")

    elsewhere = await enter(client, other.invited.workshop_id, email)
    unknown = await enter(client, workshop_id_of(shop), demo_email("nadie"))
    for response in (elsewhere, unknown):
        assert (response.status_code, response.json()["code"]) == (
            404,
            "demo_client_not_found",
        )

    # Archivada, tampoco: ni se ofrece ni entra.
    current = await client.get(
        f"/api/v1/workshop/clients/{shop.maria['id']}", headers=shop.headers
    )
    archived = await client.post(
        f"/api/v1/workshop/clients/{shop.maria['id']}/archive",
        json={"version": current.json()["version"]},
        headers=shop.headers,
    )
    assert archived.status_code == 204, archived.text
    assert (await listed(client, workshop_id_of(shop))).json() == []
    assert (await enter(client, workshop_id_of(shop), email)).status_code == 404
    assert await links(engines) == []


@pytest.mark.asyncio
async def test_an_inactive_workshop_offers_nobody(
    client: AsyncClient, engines: Engines, demo_entry: None
) -> None:
    shop: Shop = await new_shop(client)
    email = await email_client(client, shop, shop.maria, demo_email("maria"))
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE workshops SET status = 'inactive' WHERE id = :w"),
            {"w": workshop_id_of(shop)},
        )
    assert (await listed(client, workshop_id_of(shop))).status_code == 404
    assert (await enter(client, workshop_id_of(shop), email)).status_code == 404
