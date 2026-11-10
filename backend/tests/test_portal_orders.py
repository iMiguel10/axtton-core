"""Los vehículos y las órdenes del cliente en el portal (F4 paso 4, RF-42 a RF-44).

T4 es el centro: RLS separa talleres, no clientes, así que dentro de un taller lo
único que separa a un cliente de otro es el filtro por `client_id` de la sesión.
"""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy import text

from app.infra.email import InMemoryEmailSender
from tests.conftest import Engines
from tests.test_clients import create as create_client
from tests.test_concurrency import dispose_global_engines  # noqa: F401
from tests.test_employees import add_mechanic
from tests.test_portal_auth import bearer, consume, link_for, new_email
from tests.test_quote_decision import decide
from tests.test_quote_send import cancel, diagnosing_order, draft_with_lines, send
from tests.test_quotes import ORDERS, PART, expire_by_sql, quotes_of, save
from tests.test_vehicles import change_owner
from tests.test_vehicles import create as create_vehicle
from tests.test_work_orders import Shop, force_status, new_shop, open_order, outbox
from tests.test_worklog import add_work

__all__ = ["outbox"]

PORTAL = "/api/v1/portal"
NOT_FOUND = {"code": "work_order_not_found"}


def workshop_id_of(shop: Shop) -> UUID:
    return UUID(shop.admin.headers["X-Workshop-Id"])


async def enter(
    client: AsyncClient, outbox: InMemoryEmailSender, workshop_id: UUID, email: str
) -> dict[str, str]:
    session = await consume(client, *await link_for(client, outbox, workshop_id, email))
    assert session.status_code == 204, session.text
    return bearer(session)


async def email_client(
    client: AsyncClient, shop: Shop, person: dict[str, Any], email: str | None = None
) -> str:
    """Le pone un email a un cliente de la tienda, para que pueda entrar."""
    address = email or new_email()
    response = await client.patch(
        f"/api/v1/workshop/clients/{person['id']}",
        json={"version": person["version"], "email": address},
        headers=shop.headers,
    )
    assert response.status_code == 204, response.text
    return address


@dataclass(frozen=True)
class Portal:
    shop: Shop
    maria: dict[str, str]
    luis: dict[str, str]


@pytest_asyncio.fixture
async def portal(client: AsyncClient, outbox: InMemoryEmailSender) -> Portal:
    """María (dueña del coche del taller) y Luis, los dos con sesión en el portal."""
    shop = await new_shop(client)
    workshop_id = workshop_id_of(shop)
    maria_email = await email_client(client, shop, shop.maria)
    luis_email = await email_client(client, shop, shop.luis)
    return Portal(
        shop,
        await enter(client, outbox, workshop_id, maria_email),
        await enter(client, outbox, workshop_id, luis_email),
    )


async def vehicles(
    client: AsyncClient, headers: dict[str, str]
) -> list[dict[str, Any]]:
    response = await client.get(f"{PORTAL}/vehicles", headers=headers)
    assert response.status_code == 200, response.text
    result: list[dict[str, Any]] = response.json()
    return result


async def order_ids(client: AsyncClient, headers: dict[str, str]) -> set[str]:
    return {
        order["id"]
        for vehicle in await vehicles(client, headers)
        for order in vehicle["orders"]
    }


async def read(client: AsyncClient, headers: dict[str, str], order_id: str) -> Response:
    return await client.get(f"{PORTAL}/orders/{order_id}", headers=headers)


async def detail(
    client: AsyncClient, headers: dict[str, str], order_id: str
) -> dict[str, Any]:
    response = await read(client, headers, order_id)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


async def luis_car(client: AsyncClient, shop: Shop) -> dict[str, Any]:
    return await create_vehicle(
        client, shop.headers, shop.luis["id"], plate="9999 ZZZ", make="Fiat"
    )


async def order_of_luis(client: AsyncClient, shop: Shop) -> str:
    car = await luis_car(client, shop)
    order = await open_order(client, shop.headers, car["id"])
    order_id: str = order["id"]
    return order_id


# --- T4: un cliente no lee lo de otro --------------------------------------------


@pytest.mark.asyncio
async def test_t4_a_client_of_the_same_workshop_does_not_exist_for_another(
    client: AsyncClient, portal: Portal
) -> None:
    """RLS no separa a María de Luis: los dos están en el mismo taller."""
    theirs = await order_of_luis(client, portal.shop)

    assert await order_ids(client, portal.maria) == set()
    response = await read(client, portal.maria, theirs)
    assert response.status_code == 404
    assert response.json()["code"] == NOT_FOUND["code"]
    # Luis, en cambio, la ve: la prueba no pasa porque no se vea nada.
    assert await order_ids(client, portal.luis) == {theirs}
    assert (await read(client, portal.luis, theirs)).status_code == 200


@pytest.mark.asyncio
async def test_t4_an_order_of_another_client_answers_like_one_that_never_existed(
    client: AsyncClient, portal: Portal
) -> None:
    """Si respondieran distinto, se podría saber qué órdenes hay."""
    theirs = await read(client, portal.maria, await order_of_luis(client, portal.shop))
    missing = await read(client, portal.maria, str(uuid4()))
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json()


@pytest.mark.asyncio
async def test_t4_a_client_of_another_workshop_cannot_read_it_with_the_same_email(
    client: AsyncClient, engines: Engines, outbox: InMemoryEmailSender
) -> None:
    """El mismo email en dos talleres son dos clientes, y dos sesiones distintas."""
    first = await new_shop(client)
    email = await email_client(client, first, first.maria)
    order = await open_order(client, first.headers, first.car["id"])

    # new_shop vacía la base de datos: el segundo taller se monta a mano.
    from tests.test_clients import open_workshop

    other_admin = await open_workshop(client, "Taller B")
    same = await create_client(client, other_admin.headers, name="María", email=email)
    car = await create_vehicle(client, other_admin.headers, same["id"], make="Opel")
    own = await open_order(client, other_admin.headers, car["id"])

    session_b = await enter(
        client, outbox, UUID(other_admin.headers["X-Workshop-Id"]), email
    )
    assert await order_ids(client, session_b) == {own["id"]}
    assert (await read(client, session_b, order["id"])).status_code == 404

    session_a = await enter(client, outbox, workshop_id_of(first), email)
    assert await order_ids(client, session_a) == {order["id"]}
    assert (await read(client, session_a, own["id"])).status_code == 404


@pytest.mark.asyncio
async def test_t4_no_route_accepts_a_client_chosen_by_the_caller(
    client: AsyncClient, portal: Portal
) -> None:
    """Ni parámetros ni cabeceras cambian de quién es la sesión (T10)."""
    theirs = await order_of_luis(client, portal.shop)
    luis_id = portal.shop.luis["id"]

    listed = await client.get(
        f"{PORTAL}/vehicles",
        params={"client_id": luis_id},
        headers={**portal.maria, "X-Client-Id": luis_id},
    )
    assert listed.status_code == 200
    assert listed.json() == []
    forced = await client.get(
        f"{PORTAL}/orders/{theirs}",
        params={"client_id": luis_id},
        headers={**portal.maria, "X-Client-Id": luis_id},
    )
    assert forced.status_code == 404


@pytest.mark.asyncio
async def test_t2_staff_cannot_use_the_portal_routes(
    client: AsyncClient, portal: Portal
) -> None:
    order = await open_order(client, portal.shop.headers, portal.shop.car["id"])
    for path in (f"{PORTAL}/vehicles", f"{PORTAL}/orders/{order['id']}"):
        response = await client.get(path, headers=portal.shop.headers)
        assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_without_a_session_nothing_is_read(client: AsyncClient) -> None:
    assert (await client.get(f"{PORTAL}/vehicles")).status_code == 401
    assert (await client.get(f"{PORTAL}/orders/{uuid4()}")).status_code == 401


# --- RF-44: el acceso va por la orden, no por el vehículo -------------------------


@pytest.mark.asyncio
async def test_rf44_the_new_owner_does_not_see_the_previous_owners_orders(
    client: AsyncClient, portal: Portal
) -> None:
    shop = portal.shop
    old = await open_order(client, shop.headers, shop.car["id"])
    await force_status(old["id"], "delivered")

    car = await client.get(
        f"/api/v1/workshop/vehicles/{shop.car['id']}", headers=shop.headers
    )
    await change_owner(client, shop.headers, car.json(), shop.luis["id"])
    new = await open_order(client, shop.headers, shop.car["id"])

    assert await order_ids(client, portal.luis) == {new["id"]}
    assert (await read(client, portal.luis, old["id"])).status_code == 404
    # Quien lo vendió sigue viendo la suya, y solo la suya.
    assert await order_ids(client, portal.maria) == {old["id"]}
    assert (await read(client, portal.maria, new["id"])).status_code == 404


@pytest.mark.asyncio
async def test_a_vehicle_without_orders_does_not_appear(
    client: AsyncClient, portal: Portal
) -> None:
    assert await vehicles(client, portal.maria) == []


# --- RF-42: la lista ------------------------------------------------------------


@pytest.mark.asyncio
async def test_rf42_orders_are_grouped_by_vehicle_and_speak_the_clients_language(
    client: AsyncClient, portal: Portal
) -> None:
    shop = portal.shop
    other_car = await create_vehicle(
        client, shop.headers, shop.maria["id"], plate="5555 BBB", make="Ford"
    )
    first = await open_order(client, shop.headers, shop.car["id"])
    second = await open_order(client, shop.headers, shop.car["id"])
    third = await open_order(client, shop.headers, other_car["id"])
    await force_status(second["id"], "waiting_parts")

    listed = await vehicles(client, portal.maria)

    # El coche con la última orden, primero; y dentro, la última primero.
    assert [v["make"] for v in listed] == ["Ford", "Seat"]
    assert [o["id"] for o in listed[0]["orders"]] == [third["id"]]
    assert [o["id"] for o in listed[1]["orders"]] == [second["id"], first["id"]]
    assert listed[1]["orders"][0]["progress"]["status"] == "waiting_parts"
    assert listed[1]["orders"][1]["progress"]["status"] == "in_review"
    assert set(listed[1]["orders"][1]) == {"id", "code", "opened_at", "progress"}
    assert set(listed[1]) == {"plate", "make", "model", "orders"}


@pytest.mark.asyncio
async def test_a_cancelled_order_does_not_exist_for_the_client(
    client: AsyncClient, portal: Portal
) -> None:
    shop = portal.shop
    order = await open_order(client, shop.headers, shop.car["id"])
    await force_status(order["id"], "cancelled")

    assert await vehicles(client, portal.maria) == []
    assert (await read(client, portal.maria, order["id"])).status_code == 404


@pytest.mark.asyncio
async def test_rf80_the_expected_date_that_passed_reaches_the_client(
    client: AsyncClient, portal: Portal, engines: Engines
) -> None:
    shop = portal.shop
    order = await open_order(client, shop.headers, shop.car["id"])
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "UPDATE work_orders SET expected_delivery_at ="
                " clock_timestamp() - interval '2 days' WHERE id = :o"
            ),
            {"o": order["id"]},
        )
    progress = (await detail(client, portal.maria, order["id"]))["progress"]
    assert progress["delivery_overdue"] is True
    assert progress["expected_delivery_at"] is not None


# --- RF-43: el detalle, y lo que nunca sale de él --------------------------------


@pytest.mark.asyncio
async def test_rf43_internal_things_never_reach_the_client(
    client: AsyncClient, portal: Portal
) -> None:
    """Se busca en la respuesta entera, no campo a campo: lo que preocupa es lo
    que nadie pensó en quitar."""
    shop = portal.shop
    juan = await add_mechanic(client, shop.admin, "Juanísimo")
    order_id = await diagnosing_order(client, shop)
    note = await client.post(
        f"{ORDERS}/{order_id}/notes",
        json={"body": "NOTA-SECRETA el cliente regatea"},
        headers=shop.headers,
    )
    assert note.status_code == 201, note.text
    work = await add_work(
        client,
        shop.headers,
        order_id,
        juan,
        hours="7.25",
        description="Cambio de aceite",
    )
    assert work.status_code == 201, work.text

    body = (await read(client, portal.maria, order_id)).text

    assert "Cambio de aceite" in body
    assert "NOTA-SECRETA" not in body
    assert "Juanísimo" not in body
    assert "7.25" not in body
    payload = json.loads(body)
    assert set(payload) == {
        "id",
        "code",
        "opened_at",
        "progress",
        "vehicle",
        "diagnosis",
        "quotes",
        "work",
    }
    assert set(payload["work"][0]) == {"description", "worked_on"}
    assert set(payload["diagnosis"]) == {"text", "updated_at"}


@pytest.mark.asyncio
async def test_rf22_the_client_reads_only_the_current_diagnosis(
    client: AsyncClient, portal: Portal
) -> None:
    shop = portal.shop
    order_id = await diagnosing_order(client, shop)
    corrected = await client.post(
        f"{ORDERS}/{order_id}/diagnosis",
        json={"base_version_no": 1, "text": "Discos y pastillas gastados."},
        headers=shop.headers,
    )
    assert corrected.status_code == 201, corrected.text

    body = await detail(client, portal.maria, order_id)
    assert body["diagnosis"]["text"] == "Discos y pastillas gastados."


@pytest.mark.asyncio
async def test_an_order_with_nothing_yet_says_so(
    client: AsyncClient, portal: Portal
) -> None:
    order = await open_order(client, portal.shop.headers, portal.shop.car["id"])
    body = await detail(client, portal.maria, order["id"])
    assert body["diagnosis"] is None
    assert body["quotes"] == []
    assert body["work"] == []


@pytest.mark.asyncio
async def test_a_voided_work_entry_is_work_that_was_not_done(
    client: AsyncClient, portal: Portal
) -> None:
    shop = portal.shop
    juan = await add_mechanic(client, shop.admin, "Juan")
    order = await open_order(client, shop.headers, shop.car["id"])
    wrong = await add_work(
        client, shop.headers, order["id"], juan, description="Anotado por error"
    )
    await add_work(client, shop.headers, order["id"], juan, description="Bien hecho")
    voided = await client.post(
        f"{ORDERS}/{order['id']}/work-entries/{wrong.json()['id']}/void",
        headers=shop.headers,
    )
    assert voided.status_code in (200, 204), voided.text

    body = await detail(client, portal.maria, order["id"])
    assert [w["description"] for w in body["work"]] == ["Bien hecho"]


# --- RF-43: el presupuesto ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_draft_has_not_left_the_workshop(
    client: AsyncClient, portal: Portal
) -> None:
    shop = portal.shop
    order_id = await diagnosing_order(client, shop)
    await draft_with_lines(client, shop, order_id)
    assert (await detail(client, portal.maria, order_id))["quotes"] == []


@pytest.mark.asyncio
async def test_rf43_the_current_quote_comes_first_with_the_previous_ones_after(
    client: AsyncClient, portal: Portal
) -> None:
    shop = portal.shop
    order_id = await diagnosing_order(client, shop)
    first = await draft_with_lines(client, shop, order_id)
    assert (await send(client, shop, order_id, first)).status_code == 204

    correct = await client.post(f"{ORDERS}/{order_id}/quotes", headers=shop.headers)
    assert correct.status_code == 201, correct.text
    second = correct.json()["id"]
    assert (await send(client, shop, order_id, second)).status_code == 204

    # Y un borrador más, que no debe verse aunque sea el último.
    draft = await client.post(f"{ORDERS}/{order_id}/quotes", headers=shop.headers)
    assert draft.status_code == 201, draft.text

    quotes = (await detail(client, portal.maria, order_id))["quotes"]
    assert [(q["version_no"], q["status"]) for q in quotes] == [
        (2, "sent"),
        (1, "superseded"),
    ]
    assert quotes[0]["total_cents"] == 12100
    assert quotes[0]["valid_until"] is not None


@pytest.mark.asyncio
async def test_rf39_the_global_discount_is_shown_as_such_not_spread_over_the_lines(
    client: AsyncClient, portal: Portal
) -> None:
    shop = portal.shop
    order_id = await diagnosing_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    [current] = await quotes_of(client, shop.headers, order_id)
    one_hundred = {
        "kind": "labor",
        "description": "Diagnóstico",
        "quantity": "1",
        "unit_price_cents": 10000,
        "vat_bp": 2100,
    }
    saved = await save(
        client,
        shop.headers,
        quote_id,
        current["version"],
        [one_hundred, PART],
        global_discount={"kind": "amount", "value": 1000},
    )
    assert saved.status_code == 200, saved.text
    assert (await send(client, shop, order_id, quote_id)).status_code == 204

    [quote] = (await detail(client, portal.maria, order_id))["quotes"]
    assert quote["global_discount_cents"] == 1000
    # 100 € de la primera, y 60 € con un 10 % de la segunda: sin el reparto.
    assert [line["amount_cents"] for line in quote["lines"]] == [10000, 5400]
    assert quote["subtotal_cents"] == 15400
    # RF-38: la pieza usada se ve como tal.
    assert quote["lines"][1]["part_condition"] == "used"


@pytest.mark.asyncio
async def test_a_quote_past_its_date_is_expired_for_the_client_too(
    client: AsyncClient, portal: Portal
) -> None:
    shop = portal.shop
    order_id = await diagnosing_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    assert (await send(client, shop, order_id, quote_id)).status_code == 204
    await expire_by_sql(quote_id)

    [quote] = (await detail(client, portal.maria, order_id))["quotes"]
    assert quote["status"] == "expired"


@pytest.mark.asyncio
async def test_a_recorded_decision_shows_how_but_not_who_or_the_internal_note(
    client: AsyncClient, portal: Portal
) -> None:
    shop = portal.shop
    order_id = await diagnosing_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    assert (await send(client, shop, order_id, quote_id)).status_code == 204
    decided = await decide(
        client, shop, order_id, quote_id, note="NOTA-INTERNA llamó enfadado"
    )
    assert decided.status_code == 204, decided.text

    response = await read(client, portal.maria, order_id)
    assert "NOTA-INTERNA" not in response.text
    [quote] = response.json()["quotes"]
    assert quote["status"] == "approved"
    assert set(quote["decision"]) == {"outcome", "channel", "decided_at"}
    assert quote["decision"]["channel"] == "phone"
    # RF-37: aprobada, ya hay fecha prevista.
    assert quote["delivery_on"] is not None


@pytest.mark.asyncio
async def test_the_reason_a_quote_was_withdrawn_stays_in_the_workshop(
    client: AsyncClient, portal: Portal
) -> None:
    shop = portal.shop
    order_id = await diagnosing_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    assert (await send(client, shop, order_id, quote_id)).status_code == 204
    cancelled = await cancel(client, shop, order_id, quote_id, "MOTIVO-INTERNO")
    assert cancelled.status_code == 204, cancelled.text

    response = await read(client, portal.maria, order_id)
    assert "MOTIVO-INTERNO" not in response.text
    [quote] = response.json()["quotes"]
    assert quote["status"] == "cancelled"


@pytest.mark.asyncio
async def test_access_is_checked_on_these_routes_too(
    client: AsyncClient, portal: Portal
) -> None:
    """Cada ruta pasa por la dependencia: un cliente archivado se queda fuera."""
    shop = portal.shop
    order = await open_order(client, shop.headers, shop.car["id"])
    await force_status(order["id"], "delivered")
    current = await client.get(
        f"/api/v1/workshop/clients/{shop.maria['id']}", headers=shop.headers
    )
    archived = await client.post(
        f"/api/v1/workshop/clients/{shop.maria['id']}/archive",
        json={"version": current.json()["version"]},
        headers=shop.headers,
    )
    assert archived.status_code in (200, 204), archived.text

    assert (
        await client.get(f"{PORTAL}/vehicles", headers=portal.maria)
    ).status_code == 403
    assert (await read(client, portal.maria, order["id"])).status_code == 403
