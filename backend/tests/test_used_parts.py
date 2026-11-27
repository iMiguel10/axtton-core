"""Las piezas usadas en una orden por la API (F7 paso 3, RF-93, RF-94, RF-96).

Los triggers van en test_used_parts_db.py; las carreras, en test_concurrency.py.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.api.deps import get_email_sender
from app.infra.email import InMemoryEmailSender
from app.main import app
from tests.test_clients import open_workshop
from tests.test_employees import add_mechanic, invite_and_accept
from tests.test_limits import refused
from tests.test_parts import URL as PARTS
from tests.test_parts import create as create_part
from tests.test_work_order_lifecycle import move, moved
from tests.test_work_orders import URL as ORDERS
from tests.test_work_orders import Shop, force_status, new_shop, open_order

MOVEMENTS = "/api/v1/workshop/stock-movements"


@pytest_asyncio.fixture
async def shop(client: AsyncClient) -> Shop:
    return await new_shop(client)


@pytest_asyncio.fixture
async def order(client: AsyncClient, shop: Shop) -> dict[str, Any]:
    return await open_order(client, shop.headers, shop.car["id"])


@pytest_asyncio.fixture
async def mechanic(client: AsyncClient, shop: Shop) -> AsyncIterator[dict[str, str]]:
    sender = InMemoryEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    try:
        yield await invite_and_accept(
            client, shop.admin, sender, await add_mechanic(client, shop.admin)
        )
    finally:
        app.dependency_overrides.pop(get_email_sender, None)


@pytest_asyncio.fixture
async def battery(client: AsyncClient, shop: Shop) -> dict[str, Any]:
    """Una batería que cuenta su stock, con 5 en la estantería."""
    part = await create_part(client, shop.headers)
    response = await client.post(
        f"{PARTS}/{part['id']}/stock/entries",
        json={"quantity": "5", "unit_cost_cents": 6000},
        headers=shop.headers,
    )
    assert response.status_code == 201, response.text
    return part


async def mount(
    client: AsyncClient,
    headers: dict[str, str],
    order_id: str,
    part_id: str,
    quantity: str = "1",
    status: int = 201,
) -> Any:
    response = await client.post(
        f"{ORDERS}/{order_id}/used-parts",
        json={"part_id": part_id, "quantity": quantity},
        headers=headers,
    )
    assert response.status_code == status, response.text
    return response


async def used_parts(
    client: AsyncClient, headers: dict[str, str], order_id: str
) -> list[dict[str, Any]]:
    response = await client.get(f"{ORDERS}/{order_id}/used-parts", headers=headers)
    assert response.status_code == 200, response.text
    result: list[dict[str, Any]] = response.json()
    return result


async def remove(
    client: AsyncClient, headers: dict[str, str], order_id: str, used_id: str
) -> Any:
    return await client.post(
        f"{ORDERS}/{order_id}/used-parts/{used_id}/remove", headers=headers
    )


async def stock_of(client: AsyncClient, headers: dict[str, str], part_id: str) -> Any:
    response = await client.get(f"{PARTS}/{part_id}", headers=headers)
    return response.json()["stock"]


async def movements(
    client: AsyncClient, headers: dict[str, str], part_id: str
) -> list[dict[str, Any]]:
    response = await client.get(f"{PARTS}/{part_id}/movements", headers=headers)
    result: list[dict[str, Any]] = response.json()["movements"]
    return result


# --- Montar (RF-93) ----------------------------------------------------------


@pytest.mark.asyncio
async def test_mounting_a_counted_part_takes_it_out_of_stock(
    client: AsyncClient, shop: Shop, order: dict[str, Any], battery: dict[str, Any]
) -> None:
    await mount(client, shop.headers, order["id"], battery["id"], "2")
    (used,) = await used_parts(client, shop.headers, order["id"])
    assert (used["reference"], used["description"], used["quantity"]) == (
        "BAT-70",
        "Batería 70 Ah",
        "2.000",
    )
    assert (used["part_condition"], used["warranty_months"]) == ("new", 24)
    assert used["removed_at"] is None
    assert used["removable"] is True
    assert await stock_of(client, shop.headers, battery["id"]) == "3.000"
    # El historial dice qué orden la consumió (RF-96).
    outflow = (await movements(client, shop.headers, battery["id"]))[0]
    assert (outflow["kind"], outflow["quantity"]) == ("out", "-2.000")
    assert outflow["work_order_id"] == order["id"]
    assert outflow["work_order_code"] == order["code"]


@pytest.mark.asyncio
async def test_a_part_whose_stock_is_not_counted_moves_nothing(
    client: AsyncClient, shop: Shop, order: dict[str, Any]
) -> None:
    screw = await create_part(
        client, shop.headers, reference="TORN", tracks_stock=False, min_stock=None
    )
    await mount(client, shop.headers, order["id"], screw["id"], "4")
    assert len(await used_parts(client, shop.headers, order["id"])) == 1
    assert await movements(client, shop.headers, screw["id"]) == []


@pytest.mark.asyncio
async def test_mounting_more_than_there_is_leaves_the_stock_negative(
    client: AsyncClient, shop: Shop, order: dict[str, Any], battery: dict[str, Any]
) -> None:
    """RF-94: se montó una pieza cuya entrada aún no se registró. No se impide
    el trabajo: el stock queda en negativo y se marca como incidencia."""
    await mount(client, shop.headers, order["id"], battery["id"], "6")
    response = await client.get(f"{PARTS}/{battery['id']}", headers=shop.headers)
    assert (response.json()["stock"], response.json()["stock_alert"]) == (
        "-1.000",
        "negative",
    )


@pytest.mark.asyncio
async def test_what_was_mounted_does_not_change_with_the_catalog(
    client: AsyncClient, shop: Shop, order: dict[str, Any], battery: dict[str, Any]
) -> None:
    await mount(client, shop.headers, order["id"], battery["id"])
    response = await client.patch(
        f"{PARTS}/{battery['id']}",
        json={"version": 1, "description": "Batería 74 Ah", "warranty_months": 36},
        headers=shop.headers,
    )
    assert response.status_code == 204, response.text
    (used,) = await used_parts(client, shop.headers, order["id"])
    assert (used["description"], used["warranty_months"]) == ("Batería 70 Ah", 24)


@pytest.mark.asyncio
async def test_an_archived_part_or_a_closed_order_take_no_parts(
    client: AsyncClient, shop: Shop, order: dict[str, Any], battery: dict[str, Any]
) -> None:
    old = await create_part(client, shop.headers, reference="VIEJA")
    await client.post(
        f"{PARTS}/{old['id']}/archive", json={"version": 1}, headers=shop.headers
    )
    refused(
        await mount(client, shop.headers, order["id"], old["id"], status=409),
        "part_archived",
    )
    await force_status(order["id"], "delivered")
    refused(
        await mount(client, shop.headers, order["id"], battery["id"], status=409),
        "work_order_closed",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("quantity", ["0", "-1", "1.0001", "NaN"])
async def test_an_invalid_quantity_is_a_422(
    client: AsyncClient,
    shop: Shop,
    order: dict[str, Any],
    battery: dict[str, Any],
    quantity: str,
) -> None:
    await mount(client, shop.headers, order["id"], battery["id"], quantity, status=422)


# --- Quitar (RF-93, RNF-12) ----------------------------------------------------


@pytest.mark.asyncio
async def test_removing_a_part_reverses_its_outflow_and_deletes_nothing(
    client: AsyncClient, shop: Shop, order: dict[str, Any], battery: dict[str, Any]
) -> None:
    used_id = (
        await mount(client, shop.headers, order["id"], battery["id"], "2")
    ).json()["id"]
    response = await remove(client, shop.headers, order["id"], used_id)
    assert response.status_code == 204, response.text
    (used,) = await used_parts(client, shop.headers, order["id"])
    assert used["removed_at"] is not None
    assert used["removed_by_name"] is not None
    assert used["removable"] is False
    assert await stock_of(client, shop.headers, battery["id"]) == "5.000"
    reversal, outflow, _entry = await movements(client, shop.headers, battery["id"])
    assert (reversal["kind"], reversal["quantity"], reversal["reverses_id"]) == (
        "reversal",
        "2.000",
        outflow["id"],
    )
    # Sin motivo escrito: su origen es la pieza quitada de esa orden.
    assert (reversal["note"], reversal["work_order_code"]) == (None, order["code"])
    assert outflow["reversed_by_id"] == reversal["id"]

    refused(
        await remove(client, shop.headers, order["id"], used_id),
        "used_part_already_removed",
    )


@pytest.mark.asyncio
async def test_an_outflow_is_only_undone_by_removing_its_part(
    client: AsyncClient, shop: Shop, order: dict[str, Any], battery: dict[str, Any]
) -> None:
    await mount(client, shop.headers, order["id"], battery["id"])
    outflow = (await movements(client, shop.headers, battery["id"]))[0]
    response = await client.post(
        f"{MOVEMENTS}/{outflow['id']}/reverse",
        json={"note": "Por aquí no"},
        headers=shop.headers,
    )
    refused(response, "stock_movement_not_reversible")


@pytest.mark.asyncio
async def test_a_part_is_not_removed_from_a_closed_order(
    client: AsyncClient, shop: Shop, order: dict[str, Any], battery: dict[str, Any]
) -> None:
    used_id = (await mount(client, shop.headers, order["id"], battery["id"])).json()[
        "id"
    ]
    await force_status(order["id"], "delivered")
    refused(
        await remove(client, shop.headers, order["id"], used_id), "work_order_closed"
    )
    (used,) = await used_parts(client, shop.headers, order["id"])
    assert used["removable"] is False


@pytest.mark.asyncio
async def test_an_order_with_mounted_parts_is_not_cancelled(
    client: AsyncClient, shop: Shop, order: dict[str, Any], battery: dict[str, Any]
) -> None:
    """§6: cancelar es para órdenes abiertas por error, sin piezas usadas. Una
    quitada ya no cuenta."""
    used_id = (await mount(client, shop.headers, order["id"], battery["id"])).json()[
        "id"
    ]
    response = await move(
        client, shop.headers, order["id"], "cancelled", "Abierta por error"
    )
    refused(response, "work_order_has_parts")
    await remove(client, shop.headers, order["id"], used_id)
    cancelled = await moved(
        client, shop.headers, order["id"], "cancelled", "Abierta por error"
    )
    assert cancelled["status"] == "cancelled"


# --- Quién (especificación §3) --------------------------------------------------


@pytest.mark.asyncio
async def test_a_mechanic_mounts_parts_and_removes_only_their_own(
    client: AsyncClient,
    shop: Shop,
    order: dict[str, Any],
    battery: dict[str, Any],
    mechanic: dict[str, str],
) -> None:
    mine = (await mount(client, mechanic, order["id"], battery["id"])).json()["id"]
    theirs = (await mount(client, shop.headers, order["id"], battery["id"])).json()[
        "id"
    ]
    seen = {
        u["id"]: u["removable"] for u in await used_parts(client, mechanic, order["id"])
    }
    assert seen == {mine: True, theirs: False}

    response = await remove(client, mechanic, order["id"], theirs)
    assert (response.status_code, response.json()["code"]) == (403, "not_allowed")
    assert (await remove(client, mechanic, order["id"], mine)).status_code == 204
    # El administrador quita lo de cualquiera.
    other = (await mount(client, mechanic, order["id"], battery["id"])).json()["id"]
    assert (await remove(client, shop.headers, order["id"], other)).status_code == 204


@pytest.mark.asyncio
async def test_parts_and_orders_of_another_workshop_do_not_exist(
    client: AsyncClient, shop: Shop, order: dict[str, Any], battery: dict[str, Any]
) -> None:
    used_id = (await mount(client, shop.headers, order["id"], battery["id"])).json()[
        "id"
    ]
    other = await open_workshop(client, "Taller Ajeno")
    theirs = await create_part(client, other.headers, reference="AJENA")

    # Una pieza de otro taller no se monta aquí, ni una de aquí en otro.
    response = await mount(client, shop.headers, order["id"], theirs["id"], status=404)
    assert response.json()["code"] == "part_not_found"
    for method, path in (
        ("GET", f"{ORDERS}/{order['id']}/used-parts"),
        ("POST", f"{ORDERS}/{order['id']}/used-parts/{used_id}/remove"),
    ):
        response = await client.request(method, path, headers=other.headers)
        assert response.status_code == 404, (method, path)
    response = await mount(
        client, other.headers, order["id"], battery["id"], status=404
    )
    assert response.json()["code"] == "work_order_not_found"
    assert await stock_of(client, shop.headers, battery["id"]) == "4.000"
