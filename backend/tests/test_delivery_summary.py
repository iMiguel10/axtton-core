"""El resumen de entrega (F6 paso 4: RF-53, RF-55) y los km al entregar.

Por la API, con el flujo de verdad: un presupuesto con una pieza y mano de obra,
aprobado por teléfono, un trabajo y la entrega con sus km.
"""

from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient, Response

from app.domain.delivery import add_months, warranty_of
from app.infra.email import InMemoryEmailSender
from tests.test_anonymize import anonymize, read
from tests.test_employees import add_mechanic, invite_and_accept
from tests.test_quote_decision import decide
from tests.test_quote_pdf import diagnosing_order_with_km, draft, legal_data, text_of
from tests.test_quote_send import send
from tests.test_work_orders import URL, Shop, force_status, get, outbox, shop
from tests.test_worklog import add_work

__all__ = ["outbox", "shop"]


async def pdf(client: AsyncClient, headers: dict[str, str], order_id: str) -> Response:
    return await client.get(f"{URL}/{order_id}/delivery-summary/pdf", headers=headers)


async def deliver(
    client: AsyncClient, shop: Shop, order_id: str, **body: Any
) -> Response:
    current = await get(client, shop.headers, order_id)
    return await client.post(
        f"{URL}/{order_id}/status",
        json={"version": current["version"], "to_status": "delivered", **body},
        headers=shop.headers,
    )


async def repaired_and_ready(client: AsyncClient, shop: Shop) -> str:
    """Una orden con 187.410 km a la entrada, el presupuesto aprobado (pastillas
    reacondicionadas y su mano de obra), un trabajo anotado y otro anulado, y lista."""
    order_id = await diagnosing_order_with_km(client, shop)
    quote_id = await draft(client, shop, order_id)
    assert (await send(client, shop, order_id, quote_id)).status_code == 204
    assert (await decide(client, shop, order_id, quote_id)).status_code == 204
    juan = await add_mechanic(client, shop.admin, "Juan")
    done = await add_work(client, shop.headers, order_id, juan)
    assert done.status_code == 201, done.text
    wrong = await add_work(
        client, shop.headers, order_id, juan, description="Anotado por error"
    )
    voided = await client.post(
        f"{URL}/{order_id}/work-entries/{wrong.json()['id']}/void", headers=shop.headers
    )
    assert voided.status_code == 204
    await force_status(order_id, "ready")
    return order_id


# --- La garantía (dominio) -------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "months", "expected"),
    [
        (date(2026, 11, 18), 3, date(2027, 2, 18)),
        # Un mes sin ese día: el último del mes.
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
        (date(2027, 11, 30), 3, date(2028, 2, 29)),
        (date(2026, 10, 31), 1, date(2026, 11, 30)),
    ],
)
def test_months_are_added_on_the_calendar(
    day: date, months: int, expected: date
) -> None:
    assert add_months(day, months) == expected


def test_the_warranty_is_three_months_or_2000_km() -> None:
    warranty = warranty_of(date(2026, 11, 18), 187_500, unrepaired=False)
    assert warranty is not None
    assert (warranty.until, warranty.until_km) == (date(2027, 2, 18), 189_500)
    # Sin km al entregar, solo la fecha.
    no_km = warranty_of(date(2026, 11, 18), None, unrepaired=False)
    assert no_km is not None and no_km.until_km is None
    # Sin reparar, no hay garantía de reparación.
    assert warranty_of(date(2026, 11, 18), 1, unrepaired=True) is None


# --- Los km al entregar ----------------------------------------------------------


@pytest.mark.asyncio
async def test_the_km_are_written_when_delivering(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await repaired_and_ready(client, shop)
    below = await deliver(client, shop, order_id, odometer_km=187_000)
    assert below.status_code == 422
    assert below.json()["code"] == "delivered_odometer_below_entry"

    assert (
        await deliver(client, shop, order_id, odometer_km=187_423)
    ).status_code == 204
    after = await get(client, shop.headers, order_id)
    assert (after["status"], after["delivered_odometer_km"]) == ("delivered", 187_423)


@pytest.mark.asyncio
async def test_the_km_only_go_with_the_delivery(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await diagnosing_order_with_km(client, shop)
    current = await get(client, shop.headers, order_id)
    response = await client.post(
        f"{URL}/{order_id}/status",
        json={
            "version": current["version"],
            "to_status": "ready",
            "note": "Sin reparar",
            "odometer_km": 190_000,
        },
        headers=shop.headers,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "odometer_only_on_delivery"


# --- El resumen --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_summary_has_what_rf53_asks_and_says_it_is_not_an_invoice(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await repaired_and_ready(client, shop)
    assert (
        await deliver(client, shop, order_id, odometer_km=187_423)
    ).status_code == 204
    response = await pdf(client, shop.headers, order_id)
    assert response.headers["cache-control"] == "no-store"
    content = text_of(response)
    order = await get(client, shop.headers, order_id)
    for expected in (
        "Resumen de entrega",
        "Este documento no es una factura",
        order["code"],
        "María",
        shop.car["plate"],
        "187.410 km",
        "187.423 km",
        # El trabajo sin anular, y la pieza del presupuesto aprobado.
        "Cambio de pastillas delanteras",
        "Pastillas de freno delanteras",
        "Ref. BP-1234",
        "Pieza reacondicionada",
        "Importe del presupuesto aceptado (versión 1)",
        # La garantía: 3 meses o 2.000 km desde la entrega.
        "3 meses o 2.000 km desde la entrega",
        "o los 189.423 km",
    ):
        assert expected in content, expected
    assert "Anotado por error" not in content
    # La mano de obra no es una pieza.
    assert "Cambio de pastillas Mano" not in content


@pytest.mark.asyncio
async def test_rf55_the_summary_comes_out_identical(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await repaired_and_ready(client, shop)
    assert (
        await deliver(client, shop, order_id, odometer_km=187_423)
    ).status_code == 204
    first = await pdf(client, shop.headers, order_id)
    # Lo que se escribe en una orden cerrada (una nota, el cobro) no lo cambia.
    note = await client.post(
        f"{URL}/{order_id}/notes",
        json={"body": "Pagará el viernes"},
        headers=shop.headers,
    )
    assert note.status_code == 201, note.text
    assert (await pdf(client, shop.headers, order_id)).content == first.content


@pytest.mark.asyncio
async def test_an_unrepaired_delivery_has_no_repair_warranty(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await diagnosing_order_with_km(client, shop)
    current = await get(client, shop.headers, order_id)
    unrepaired = await client.post(
        f"{URL}/{order_id}/status",
        json={
            "version": current["version"],
            "to_status": "ready",
            "note": "El cliente no quiere repararlo",
        },
        headers=shop.headers,
    )
    assert unrepaired.status_code == 204, unrepaired.text
    assert (await deliver(client, shop, order_id)).status_code == 204
    content = text_of(await pdf(client, shop.headers, order_id))
    assert "Entregado sin reparar" in content
    assert "no hay garantía de reparación" in content
    assert "Importe del presupuesto" not in content
    # Sin km al entregar: no se anotaron.
    assert "Sin anotar" in content


@pytest.mark.asyncio
async def test_an_order_not_delivered_has_no_summary(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await repaired_and_ready(client, shop)
    response = await pdf(client, shop.headers, order_id)
    assert response.status_code == 409
    assert response.json()["code"] == "work_order_not_delivered"


@pytest.mark.asyncio
async def test_the_client_name_disappears_when_anonymized(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await repaired_and_ready(client, shop)
    assert (await deliver(client, shop, order_id)).status_code == 204
    maria = await read(client, shop.headers, shop.maria["id"])
    assert (await anonymize(client, shop.headers, maria)).status_code == 204
    content = text_of(await pdf(client, shop.headers, order_id))
    assert "Cliente eliminado" in content
    assert "María" not in content


@pytest.mark.asyncio
async def test_a_mechanic_who_cannot_see_prices_gets_no_summary(
    client: AsyncClient, shop: Shop, outbox: InMemoryEmailSender
) -> None:
    order_id = await repaired_and_ready(client, shop)
    assert (await deliver(client, shop, order_id)).status_code == 204
    mechanic = await invite_and_accept(
        client, shop.admin, outbox, await add_mechanic(client, shop.admin, "Pepe")
    )
    assert (await pdf(client, mechanic, order_id)).status_code == 200
    await legal_data(client, shop, mechanics_see_sale_prices=False)
    refused = await pdf(client, mechanic, order_id)
    assert refused.status_code == 403
    assert refused.json()["code"] == "quote_prices_hidden"
