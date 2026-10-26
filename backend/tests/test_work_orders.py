"""Órdenes de trabajo por la API (RF-20 a RF-25, RF-26, RNF-01, RNF-15).

Lo que garantiza la base de datos (invariante 5, append-only, contadores) está
en test_work_orders_db.py; las aperturas simultáneas, en test_concurrency.py.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.deps import get_email_sender
from app.infra.email import InMemoryEmailSender
from app.main import app
from app.scripts.reset_data import truncate_all
from tests.test_clients import create as create_client
from tests.test_clients import open_workshop
from tests.test_employees import AdminSession, add_mechanic, invite_and_accept
from tests.test_vehicles import change_owner
from tests.test_vehicles import create as create_vehicle
from tests.test_vehicles import get as get_vehicle

URL = "/api/v1/workshop/orders"


@dataclass(frozen=True)
class Shop:
    admin: AdminSession
    maria: dict[str, Any]
    luis: dict[str, Any]
    car: dict[str, Any]

    @property
    def headers(self) -> dict[str, str]:
        return self.admin.headers


@pytest_asyncio.fixture
async def outbox() -> AsyncIterator[InMemoryEmailSender]:
    sender = InMemoryEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    yield sender
    app.dependency_overrides.pop(get_email_sender, None)


@pytest_asyncio.fixture
async def shop(client: AsyncClient) -> Shop:
    """Talleres Pérez, con Ana (administradora), María y Luis, y el coche de María."""
    await truncate_all()
    admin = await open_workshop(client, "Talleres Pérez")
    maria = await create_client(client, admin.headers, name="María")
    luis = await create_client(client, admin.headers, name="Luis", phone="611")
    car = await create_vehicle(client, admin.headers, maria["id"], make="Seat")
    return Shop(admin, maria, luis, car)


async def open_order(
    client: AsyncClient, headers: dict[str, str], vehicle_id: str, **fields: Any
) -> dict[str, Any]:
    body = {"vehicle_id": vehicle_id, "type": "breakdown", **fields}
    response = await client.post(URL, json=body, headers=headers)
    assert response.status_code == 201, response.text
    return await get(client, headers, response.json()["id"])


async def get(client: AsyncClient, headers: dict[str, str], order_id: str) -> Any:
    response = await client.get(f"{URL}/{order_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def codes(client: AsyncClient, headers: dict[str, str], **params: Any) -> list:
    response = await client.get(URL, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return [o["code"] for o in response.json()]


async def force_status(order_id: str, status: str) -> None:
    """Lleva una orden a un estado escribiendo también su cambio, como lo hará el
    paso 4: con el rol de plataforma (se salta RLS, no el trigger del invariante 5)."""
    import os

    engine = create_async_engine(os.environ["PLATFORM_DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO work_order_status_changes"
                    " (workshop_id, work_order_id, from_status, to_status, cause)"
                    " SELECT workshop_id, id, status, :s, 'manual'"
                    " FROM work_orders WHERE id = :o"
                ),
                {"o": order_id, "s": status},
            )
            await conn.execute(
                text("UPDATE work_orders SET status = :s WHERE id = :o"),
                {"o": order_id, "s": status},
            )
    finally:
        await engine.dispose()


# --- Abrir (RF-20, RF-21) ----------------------------------------------------


@pytest.mark.asyncio
async def test_an_order_is_opened_for_the_current_owner_with_its_first_change(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(
        client,
        shop.headers,
        shop.car["id"],
        odometer_km=123456,
        reason="Ruido al frenar",
        expected_delivery_at="2026-11-02T18:00:00+01:00",
        dropped_off_by_name="Pepe (su hijo)",
        dropped_off_by_phone="622",
        reception_notes="Rayón en la puerta trasera",
    )
    assert order["code"] == f"OT-{order['year']}-0001"
    assert (order["status"], order["type"]) == ("received", "breakdown")
    # El cliente no se elige: es el titular del coche al abrirla.
    assert order["client"] == {
        "id": shop.maria["id"],
        "name": "María",
        "phone": "600 111 222",
    }
    assert order["vehicle"]["plate"] == "1234 BCD"
    assert (order["odometer_km"], order["reason"]) == (123456, "Ruido al frenar")
    # Invariante 5 desde el primer momento: el estado es el de su único cambio.
    [opened] = order["history"]
    assert (opened["from_status"], opened["to_status"], opened["cause"]) == (
        None,
        "received",
        "opened",
    )
    assert opened["employee_name"] == "Ana López"


@pytest.mark.asyncio
async def test_numbers_are_consecutive_per_workshop(
    client: AsyncClient, shop: Shop
) -> None:
    first = await open_order(client, shop.headers, shop.car["id"])
    second = await open_order(client, shop.headers, shop.car["id"])
    assert (first["number"], second["number"]) == (1, 2)

    b = (await open_workshop(client, "Taller B")).headers
    ana_b = await create_client(client, b, name="Ana de B")
    car_b = await create_vehicle(client, b, ana_b["id"])
    # Cada taller lleva su propia cuenta.
    assert (await open_order(client, b, car_b["id"]))["number"] == 1


@pytest.mark.asyncio
async def test_changing_the_owner_does_not_change_the_client_of_open_orders(
    client: AsyncClient, shop: Shop
) -> None:
    """Invariante 7 (RF-12): la orden es de quien era titular al abrirla."""
    before = await open_order(client, shop.headers, shop.car["id"])
    car = await get_vehicle(client, shop.headers, shop.car["id"])
    assert (
        await change_owner(client, shop.headers, car, shop.luis["id"])
    ).status_code == 204
    after = await open_order(client, shop.headers, shop.car["id"])

    assert (await get(client, shop.headers, before["id"]))["client"]["name"] == "María"
    assert after["client"]["name"] == "Luis"
    of_maria = await codes(client, shop.headers, client_id=shop.maria["id"])
    assert of_maria == [before["code"]]


@pytest.mark.asyncio
async def test_an_order_cannot_be_opened_for_an_archived_owner(
    client: AsyncClient, shop: Shop
) -> None:
    await client.post(
        f"/api/v1/workshop/clients/{shop.maria['id']}/archive",
        json={"version": shop.maria["version"]},
        headers=shop.headers,
    )
    response = await client.post(
        URL, json={"vehicle_id": shop.car["id"], "type": "itv"}, headers=shop.headers
    )
    assert (response.status_code, response.json()) == (409, {"code": "client_archived"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"type": "otro"},
        {"type": "itv", "odometer_km": -1},
        # Una hora sin zona no dice qué instante es.
        {"type": "itv", "expected_delivery_at": "2026-11-02T18:00:00"},
    ],
)
async def test_invalid_data_is_a_422(
    client: AsyncClient, shop: Shop, body: dict[str, Any]
) -> None:
    response = await client.post(
        URL, json={"vehicle_id": shop.car["id"], **body}, headers=shop.headers
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_the_responsible_is_an_active_card_of_this_workshop(
    client: AsyncClient, shop: Shop
) -> None:
    juan = await add_mechanic(client, shop.admin, "Juan")
    order = await open_order(
        client, shop.headers, shop.car["id"], responsible_employee_id=juan
    )
    assert order["responsible"] == {"id": juan, "name": "Juan"}

    await client.patch(
        f"/api/v1/workshop/employees/{juan}",
        json={"version": 1, "active": False},
        headers=shop.headers,
    )
    inactive = await client.post(
        URL,
        json={
            "vehicle_id": shop.car["id"],
            "type": "itv",
            "responsible_employee_id": juan,
        },
        headers=shop.headers,
    )
    assert (inactive.status_code, inactive.json()) == (
        404,
        {"code": "employee_not_found"},
    )


# --- Garantía (§6) -----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_warranty_order_links_to_a_delivered_order_of_the_same_vehicle(
    client: AsyncClient, shop: Shop
) -> None:
    original = await open_order(client, shop.headers, shop.car["id"])
    body = {"vehicle_id": shop.car["id"], "warranty_of_id": original["id"]}

    not_warranty = await client.post(
        URL, json={**body, "type": "breakdown"}, headers=shop.headers
    )
    assert (not_warranty.status_code, not_warranty.json()) == (
        422,
        {"code": "warranty_of_requires_warranty_type"},
    )
    not_delivered = await client.post(
        URL, json={**body, "type": "warranty"}, headers=shop.headers
    )
    assert (not_delivered.status_code, not_delivered.json()) == (
        409,
        {"code": "warranty_of_not_delivered"},
    )

    other_car = await create_vehicle(
        client, shop.headers, shop.luis["id"], plate="9999ZZZ"
    )
    other = await client.post(
        URL,
        json={
            "vehicle_id": other_car["id"],
            "type": "warranty",
            "warranty_of_id": original["id"],
        },
        headers=shop.headers,
    )
    assert (other.status_code, other.json()) == (404, {"code": "work_order_not_found"})

    await force_status(original["id"], "delivered")
    warranty = await open_order(
        client,
        shop.headers,
        shop.car["id"],
        type="warranty",
        warranty_of_id=original["id"],
    )
    assert warranty["warranty_of"] == {"id": original["id"], "code": original["code"]}


# --- Listado (RF-24) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_the_list_filters_by_state_status_vehicle_and_responsible(
    client: AsyncClient, shop: Shop
) -> None:
    juan = await add_mechanic(client, shop.admin, "Juan")
    first = await open_order(client, shop.headers, shop.car["id"])
    second = await open_order(
        client, shop.headers, shop.car["id"], responsible_employee_id=juan
    )
    luis_car = await create_vehicle(
        client, shop.headers, shop.luis["id"], plate="5678CDF"
    )
    third = await open_order(client, shop.headers, luis_car["id"])
    await force_status(first["id"], "delivered")

    # Por defecto, las abiertas, las últimas primero.
    assert await codes(client, shop.headers) == [third["code"], second["code"]]
    assert await codes(client, shop.headers, state="closed") == [first["code"]]
    assert len(await codes(client, shop.headers, state="all")) == 3
    assert await codes(client, shop.headers, state="all", status="delivered") == [
        first["code"]
    ]
    # Un estado que no es del grupo pedido no aparece.
    assert await codes(client, shop.headers, state="open", status="delivered") == []
    assert await codes(client, shop.headers, responsible_id=juan) == [second["code"]]
    assert await codes(
        client, shop.headers, state="all", vehicle_id=shop.car["id"]
    ) == [
        second["code"],
        first["code"],
    ]


@pytest.mark.asyncio
async def test_stalled_orders_come_first_when_asked(
    client: AsyncClient, shop: Shop
) -> None:
    older = await open_order(client, shop.headers, shop.car["id"])
    newer = await open_order(client, shop.headers, shop.car["id"])
    assert await codes(client, shop.headers, sort="stalled") == [
        older["code"],
        newer["code"],
    ]


@pytest.mark.asyncio
async def test_mine_shows_a_mechanic_the_orders_they_are_responsible_for(
    client: AsyncClient, shop: Shop, outbox: InMemoryEmailSender
) -> None:
    juan = await add_mechanic(client, shop.admin, "Juan")
    mechanic = await invite_and_accept(client, shop.admin, outbox, juan)
    await open_order(client, shop.headers, shop.car["id"])
    his = await open_order(
        client, shop.headers, shop.car["id"], responsible_employee_id=juan
    )

    assert await codes(client, mechanic, mine=True) == [his["code"]]
    # Es un filtro, no una restricción: el mecánico ve todas (especificación §3).
    assert len(await codes(client, mechanic)) == 2
    assert (await client.get(f"{URL}/{his['id']}", headers=mechanic)).status_code == 200

    for response in (
        await client.post(
            URL, json={"vehicle_id": shop.car["id"], "type": "itv"}, headers=mechanic
        ),
        await client.patch(
            f"{URL}/{his['id']}",
            json={"version": his["version"], "reason": "x"},
            headers=mechanic,
        ),
    ):
        assert (response.status_code, response.json()) == (403, {"code": "not_allowed"})


# --- Edición (RF-20, RF-25, RF-26, RNF-15) ----------------------------------


@pytest.mark.asyncio
async def test_the_reception_and_the_responsible_can_be_edited(
    client: AsyncClient, shop: Shop
) -> None:
    juan = await add_mechanic(client, shop.admin, "Juan")
    order = await open_order(client, shop.headers, shop.car["id"], reason="Ruido")
    response = await client.patch(
        f"{URL}/{order['id']}",
        json={
            "version": order["version"],
            "responsible_employee_id": juan,
            "reason": "",
        },
        headers=shop.headers,
    )
    assert response.status_code == 204
    after = await get(client, shop.headers, order["id"])
    assert (after["responsible"]["name"], after["reason"]) == ("Juan", None)
    assert after["version"] == order["version"] + 1

    unassigned = await client.patch(
        f"{URL}/{order['id']}",
        json={"version": after["version"], "responsible_employee_id": None},
        headers=shop.headers,
    )
    assert unassigned.status_code == 204
    assert (await get(client, shop.headers, order["id"]))["responsible"] is None


@pytest.mark.asyncio
async def test_editing_with_an_old_version_is_a_409(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    for reason, expected in (("Primero", 204), ("Segundo", 409)):
        response = await client.patch(
            f"{URL}/{order['id']}",
            json={"version": order["version"], "reason": reason},
            headers=shop.headers,
        )
        assert response.status_code == expected
    assert (await get(client, shop.headers, order["id"]))["reason"] == "Primero"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["delivered", "cancelled"])
async def test_a_closed_order_cannot_be_edited(
    client: AsyncClient, shop: Shop, status: str
) -> None:
    """RF-26: una orden entregada o cancelada solo admite notas y su cobro."""
    order = await open_order(client, shop.headers, shop.car["id"])
    await force_status(order["id"], status)
    response = await client.patch(
        f"{URL}/{order['id']}",
        json={"version": order["version"], "reason": "x"},
        headers=shop.headers,
    )
    assert (response.status_code, response.json()) == (
        409,
        {"code": "work_order_closed"},
    )


# --- Aislamiento entre talleres (RNF-01, RNF-07) ----------------------------


@pytest.mark.asyncio
async def test_orders_vehicles_and_cards_of_another_workshop_do_not_exist(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    b_admin = await open_workshop(client, "Taller B")
    b = b_admin.headers
    juan_b = await add_mechanic(client, b_admin, "Juan de B")

    for response in (
        await client.get(f"{URL}/{order['id']}", headers=b),
        await client.patch(
            f"{URL}/{order['id']}", json={"version": 1, "reason": "x"}, headers=b
        ),
    ):
        assert (response.status_code, response.json()) == (
            404,
            {"code": "work_order_not_found"},
        )
    assert await codes(client, b, state="all") == []

    # Desde B no se abre una orden para el coche de A...
    stolen = await client.post(
        URL, json={"vehicle_id": shop.car["id"], "type": "itv"}, headers=b
    )
    assert (stolen.status_code, stolen.json()) == (404, {"code": "vehicle_not_found"})
    # ...ni desde A se asigna como responsable a una ficha de B.
    foreign = await client.patch(
        f"{URL}/{order['id']}",
        json={"version": order["version"], "responsible_employee_id": juan_b},
        headers=shop.headers,
    )
    assert (foreign.status_code, foreign.json()) == (
        404,
        {"code": "employee_not_found"},
    )
