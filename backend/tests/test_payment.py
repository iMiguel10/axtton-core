"""El cobro de una orden (RF-26, RF-28, RF-29).

Por la API: cuándo se puede registrar, qué exige y quién; y el listado de
entregadas pendientes. Al final, lo que garantiza la base de datos aunque el
código fallara.
"""

import os
from datetime import date, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.infra.email import InMemoryEmailSender
from tests.conftest import Engines, TwoWorkshops
from tests.test_employees import add_mechanic, invite_and_accept
from tests.test_vehicles import create as create_vehicle
from tests.test_work_orders import URL, Shop, get, new_shop, open_order, outbox
from tests.test_work_orders_db import Order, seed_order

__all__ = ["outbox"]


@pytest_asyncio.fixture
async def shop(client: AsyncClient) -> Shop:
    return await new_shop(client)


async def deliver(order_id: str, days_ago: int = 0) -> None:
    """Entrega una orden hace `days_ago` días, como lo haría el ciclo de vida:
    con su cambio en el historial y su fecha de entrega."""
    engine = create_async_engine(os.environ["PLATFORM_DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO work_order_status_changes"
                    " (workshop_id, work_order_id, from_status, to_status, cause)"
                    " SELECT workshop_id, id, status, 'delivered', 'manual'"
                    " FROM work_orders WHERE id = :o"
                ),
                {"o": order_id},
            )
            # Hace `days_ago` días del calendario del taller, a mediodía: restar
            # días de 24 h en UTC cruza un cambio de hora y puede caer en otro
            # día local (a finales de octubre, 9×24 h atrás son 8 días en Madrid).
            await conn.execute(
                text(
                    "UPDATE work_orders SET status = 'delivered',"
                    " delivered_at = CASE WHEN :d = 0 THEN clock_timestamp() ELSE"
                    " (((clock_timestamp() AT TIME ZONE w.timezone)::date - :d)"
                    " + time '12:00') AT TIME ZONE w.timezone END"
                    " FROM workshops w"
                    " WHERE work_orders.id = :o AND w.id = work_orders.workshop_id"
                ),
                {"o": order_id, "d": days_ago},
            )
    finally:
        await engine.dispose()


async def pay(
    client: AsyncClient, headers: dict[str, str], order: dict[str, Any], **body: Any
) -> Any:
    return await client.put(
        f"{URL}/{order['id']}/payment",
        json={"version": order["version"], **body},
        headers=headers,
    )


PAID = {
    "status": "paid",
    "method": "card",
    "amount_cents": 18_950,
    "paid_on": "2026-10-20",
}


@pytest.mark.asyncio
async def test_an_open_order_is_not_charged_yet(
    client: AsyncClient, shop: Shop
) -> None:
    """RF-28: al entregar, o después. Antes, ni se ofrece ni se acepta."""
    order = await open_order(client, shop.headers, shop.car["id"])
    assert (order["payment_status"], order["can_record_payment"]) == ("pending", False)
    response = await pay(client, shop.headers, order, **PAID)
    assert (response.status_code, response.json()) == (409, {"code": "payment_not_now"})


@pytest.mark.asyncio
async def test_a_delivered_order_is_charged_and_it_is_audited(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    await deliver(order["id"])
    order = await get(client, shop.headers, order["id"])
    assert order["can_record_payment"] is True

    assert (await pay(client, shop.headers, order, **PAID)).status_code == 204
    paid = await get(client, shop.headers, order["id"])
    assert {k: paid[k] for k in ("payment_status", "payment_method")} == {
        "payment_status": "paid",
        "payment_method": "card",
    }
    assert (paid["paid_amount_cents"], paid["paid_on"]) == (18_950, "2026-10-20")
    assert paid["version"] == order["version"] + 1

    # Se corrige: era en efectivo. En la auditoría, solo lo que cambió.
    fixed = await pay(client, shop.headers, paid, **{**PAID, "method": "cash"})
    assert fixed.status_code == 204
    audit = await client.get("/api/v1/workshop/audit", headers=shop.headers)
    entries = [e for e in audit.json()["entries"] if e["action"] == "payment_recorded"]
    assert [e["details"] for e in entries] == [
        {"payment_method": ["card", "cash"]},
        {
            "payment_status": ["pending", "paid"],
            "payment_method": [None, "card"],
            "paid_amount_cents": [None, 18_950],
            "paid_on": [None, "2026-10-20"],
        },
    ]
    assert entries[0]["target_name"] == order["code"]


@pytest.mark.asyncio
async def test_back_to_pending_or_no_charge_clears_the_details(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    await deliver(order["id"])
    order = await get(client, shop.headers, order["id"])
    await pay(client, shop.headers, order, **PAID)
    for status in ("no_charge", "pending"):
        order = await get(client, shop.headers, order["id"])
        # Lo que venga de más se ignora: sin cobrar no hay forma ni importe.
        assert (
            await pay(client, shop.headers, order, **{**PAID, "status": status})
        ).status_code == 204
        after = await get(client, shop.headers, order["id"])
        assert (
            after["payment_status"],
            after["payment_method"],
            after["paid_amount_cents"],
            after["paid_on"],
        ) == (status, None, None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"status": "paid"}, "payment_details_required"),
        ({**PAID, "method": None}, "payment_details_required"),
        ({**PAID, "paid_on": None}, "payment_details_required"),
        (
            {**PAID, "paid_on": (date.today() + timedelta(days=2)).isoformat()},
            "paid_on_in_future",
        ),
    ],
)
async def test_a_payment_needs_its_details_and_cannot_be_tomorrow(
    client: AsyncClient, shop: Shop, body: dict[str, Any], code: str
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    await deliver(order["id"])
    order = await get(client, shop.headers, order["id"])
    response = await pay(client, shop.headers, order, **body)
    assert (response.status_code, response.json()) == (422, {"code": code})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {**PAID, "amount_cents": 0},
        {**PAID, "amount_cents": -100},
        {**PAID, "method": "bitcoin"},
        {**PAID, "status": "half"},
    ],
)
async def test_impossible_values_are_a_422(
    client: AsyncClient, shop: Shop, body: dict[str, Any]
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    await deliver(order["id"])
    order = await get(client, shop.headers, order["id"])
    assert (await pay(client, shop.headers, order, **body)).status_code == 422


@pytest.mark.asyncio
async def test_charging_over_an_old_version_is_a_409(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    await deliver(order["id"])
    order = await get(client, shop.headers, order["id"])
    await pay(client, shop.headers, order, **PAID)
    stale = await pay(client, shop.headers, order, **{**PAID, "method": "cash"})
    assert (stale.status_code, stale.json()) == (
        409,
        {"code": "modified_by_someone_else"},
    )


@pytest.mark.asyncio
async def test_a_mechanic_sees_the_payment_but_cannot_record_it(
    client: AsyncClient, shop: Shop, outbox: InMemoryEmailSender
) -> None:
    mechanic = await invite_and_accept(
        client, shop.admin, outbox, await add_mechanic(client, shop.admin)
    )
    order = await open_order(client, shop.headers, shop.car["id"])
    await deliver(order["id"])
    seen = await get(client, mechanic, order["id"])
    assert (seen["payment_status"], seen["can_record_payment"]) == ("pending", False)
    response = await pay(client, mechanic, seen, **PAID)
    assert (response.status_code, response.json()) == (403, {"code": "not_allowed"})


# --- Pendientes de cobro (RF-29) ---------------------------------------------


@pytest.mark.asyncio
async def test_unpaid_lists_delivered_pending_orders_oldest_first(
    client: AsyncClient, shop: Shop
) -> None:
    other_car = await create_vehicle(
        client, shop.headers, shop.luis["id"], plate="5678 CDF"
    )
    recent = await open_order(client, shop.headers, shop.car["id"])
    old = await open_order(client, shop.headers, other_car["id"])
    paid = await open_order(client, shop.headers, shop.car["id"])
    free = await open_order(client, shop.headers, shop.car["id"])
    await open_order(client, shop.headers, shop.car["id"])  # sigue abierta
    await deliver(recent["id"], days_ago=2)
    await deliver(old["id"], days_ago=9)
    for order, status in ((paid, PAID), (free, {"status": "no_charge"})):
        await deliver(order["id"], days_ago=20)
        await pay(
            client, shop.headers, await get(client, shop.headers, order["id"]), **status
        )

    response = await client.get(f"{URL}/unpaid", headers=shop.headers)
    assert response.status_code == 200, response.text
    assert [(o["code"], o["days_pending"]) for o in response.json()] == [
        (old["code"], 9),
        (recent["code"], 2),
    ]
    assert response.json()[0]["client"]["name"] == "Luis"


@pytest.mark.asyncio
async def test_unpaid_of_another_workshop_are_not_listed(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    await deliver(order["id"], days_ago=1)
    other = await new_shop_without_reset(client)
    response = await client.get(f"{URL}/unpaid", headers=other)
    assert (response.status_code, response.json()) == (200, [])
    foreign = await client.put(
        f"{URL}/{order['id']}/payment",
        json={"version": 1, **PAID},
        headers=other,
    )
    assert (foreign.status_code, foreign.json()) == (
        404,
        {"code": "work_order_not_found"},
    )


async def new_shop_without_reset(client: AsyncClient) -> dict[str, str]:
    from tests.test_clients import open_workshop

    return (await open_workshop(client, "Talleres Gómez")).headers


# --- Lo que garantiza la base de datos ---------------------------------------


@pytest_asyncio.fixture
async def order(engines: Engines, two_workshops: TwoWorkshops) -> Order:
    return await seed_order(engines, two_workshops)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "values", "constraint"),
    [
        # Una orden abierta no está cobrada.
        ("received", "'paid', 'cash', 100, current_date", "payment_when_closed"),
        # Cobrada sin forma, importe o fecha.
        ("delivered", "'paid', NULL, 100, current_date", "payment_details"),
        ("delivered", "'paid', 'cash', NULL, current_date", "payment_details"),
        ("delivered", "'paid', 'cash', 100, NULL", "payment_details"),
        # Pendiente con detalles de un cobro.
        ("delivered", "'pending', 'cash', NULL, NULL", "payment_details"),
        ("delivered", "'no_charge', NULL, 100, NULL", "payment_details"),
    ],
)
async def test_the_database_keeps_the_payment_consistent(
    engines: Engines, order: Order, status: str, values: str, constraint: str
) -> None:
    """Con el rol de plataforma, que se salta RLS pero no los CHECK."""
    with pytest.raises(IntegrityError, match=f"ck_work_orders_{constraint}"):
        async with engines.platform.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE work_orders SET (status, payment_status, payment_method,"
                    f" paid_amount_cents, paid_on) = (:s, {values}) WHERE id = :o"
                ),
                {"s": status, "o": order.order_id},
            )
