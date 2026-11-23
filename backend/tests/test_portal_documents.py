"""La hoja de recepción y el resumen de entrega en el portal (F6 paso 6: RF-53,
RF-54, T4).

El cliente descarga la hoja solo firmada (decidido por el usuario) y el resumen
solo entregada, de sus órdenes y de nada más; la orden le dice qué hay y hasta
cuándo dura la garantía.
"""

from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient, Response

from app.domain.delivery import add_months
from tests.test_delivery_summary import deliver, repaired_and_ready
from tests.test_delivery_summary import pdf as workshop_summary
from tests.test_portal_orders import PORTAL, Portal, detail, order_of_luis, portal
from tests.test_portal_pdf import client_pdf, limiter
from tests.test_quote_pdf import text_of
from tests.test_reception import sign_on_screen
from tests.test_work_orders import URL, get, open_order, outbox

__all__ = ["limiter", "outbox", "portal"]


async def sheet(
    client: AsyncClient, headers: dict[str, str], order_id: str
) -> Response:
    return await client.get(
        f"{PORTAL}/orders/{order_id}/reception-sheet/pdf", headers=headers
    )


async def summary(
    client: AsyncClient, headers: dict[str, str], order_id: str
) -> Response:
    return await client.get(
        f"{PORTAL}/orders/{order_id}/delivery-summary/pdf", headers=headers
    )


async def signed_order(client: AsyncClient, portal: Portal) -> dict[str, Any]:
    order = await open_order(
        client, portal.shop.headers, portal.shop.car["id"], odometer_km=123_456
    )
    signed = await sign_on_screen(client, portal.shop.headers, order)
    assert signed.status_code == 204, signed.text
    return order


# --- La hoja de recepción ------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_client_downloads_the_signed_sheet_without_who_collected_it(
    client: AsyncClient, portal: Portal
) -> None:
    order = await signed_order(client, portal)
    assert (await detail(client, portal.maria, order["id"]))["documents"] == {
        "reception_sheet": True,
        "delivery_summary": False,
    }
    response = await sheet(client, portal.maria, order["id"])
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    content = text_of(response)
    assert "Jaime Sánchez" in content
    assert "123.456 km" in content
    # El taller ve quién la recogió; el cliente, no (como en el presupuesto).
    workshop = await client.get(
        f"{URL}/{order['id']}/reception-sheet/pdf", headers=portal.shop.headers
    )
    assert "Recogida en el taller por" in text_of(workshop)
    assert "Recogida en el taller por" not in content


@pytest.mark.asyncio
async def test_an_unsigned_sheet_is_not_in_the_portal(
    client: AsyncClient, portal: Portal
) -> None:
    order = await open_order(client, portal.shop.headers, portal.shop.car["id"])
    assert (await detail(client, portal.maria, order["id"]))["documents"] == {
        "reception_sheet": False,
        "delivery_summary": False,
    }
    response = await sheet(client, portal.maria, order["id"])
    assert response.status_code == 404
    assert response.json()["code"] == "reception_sheet_not_found"


@pytest.mark.asyncio
async def test_t4_nobody_else_downloads_them(
    client: AsyncClient, portal: Portal
) -> None:
    """Luis no descarga los de María, ni María los de Luis; una orden que no
    existe responde igual."""
    maria_order = await signed_order(client, portal)
    luis_order = await order_of_luis(client, portal.shop)
    for headers, order_id in (
        (portal.luis, maria_order["id"]),
        (portal.maria, luis_order),
        (portal.maria, str(uuid4())),
    ):
        for download in (sheet, summary):
            response = await download(client, headers, order_id)
            assert response.status_code == 404, (download.__name__, order_id)
            assert response.json()["code"] == "work_order_not_found"


@pytest.mark.asyncio
async def test_a_cancelled_order_has_no_sheet_even_if_signed(
    client: AsyncClient, portal: Portal
) -> None:
    order = await signed_order(client, portal)
    current = await get(client, portal.shop.headers, order["id"])
    cancelled = await client.post(
        f"{URL}/{order['id']}/status",
        json={
            "version": current["version"],
            "to_status": "cancelled",
            "note": "Abierta por error",
        },
        headers=portal.shop.headers,
    )
    assert cancelled.status_code == 204, cancelled.text
    response = await sheet(client, portal.maria, order["id"])
    assert response.status_code == 404
    assert response.json()["code"] == "work_order_not_found"


# --- El resumen de entrega y la garantía ----------------------------------------------


@pytest.mark.asyncio
async def test_the_summary_is_the_workshops_document_and_the_warranty_is_shown(
    client: AsyncClient, portal: Portal
) -> None:
    order_id = await repaired_and_ready(client, portal.shop)
    ready = await detail(client, portal.maria, order_id)
    assert ready["documents"]["delivery_summary"] is False
    assert ready["warranty"] is None
    refused = await summary(client, portal.maria, order_id)
    assert refused.status_code == 409
    assert refused.json()["code"] == "work_order_not_delivered"

    delivered = await deliver(client, portal.shop, order_id, odometer_km=187_423)
    assert delivered.status_code == 204
    found = await detail(client, portal.maria, order_id)
    assert found["documents"]["delivery_summary"] is True
    # Entregada hoy, en el calendario del taller (Madrid): tres meses o 2.000 km.
    today = datetime.now(ZoneInfo("Europe/Madrid")).date()
    assert found["warranty"] == {
        "until": add_months(today, 3).isoformat(),
        "until_km": 189_423,
    }

    response = await summary(client, portal.maria, order_id)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    # El mismo documento que descarga el taller, byte a byte.
    workshop = await workshop_summary(client, portal.shop.headers, order_id)
    assert response.content == workshop.content


@pytest.mark.asyncio
async def test_an_unrepaired_delivery_has_a_summary_and_no_warranty(
    client: AsyncClient, portal: Portal
) -> None:
    order = await open_order(client, portal.shop.headers, portal.shop.car["id"])
    current = await get(client, portal.shop.headers, order["id"])
    moved = await client.post(
        f"{URL}/{order['id']}/status",
        json={"version": current["version"], "to_status": "diagnosing"},
        headers=portal.shop.headers,
    )
    assert moved.status_code == 204, moved.text
    current = await get(client, portal.shop.headers, order["id"])
    unrepaired = await client.post(
        f"{URL}/{order['id']}/status",
        json={
            "version": current["version"],
            "to_status": "ready",
            "note": "El cliente no quiere repararlo",
        },
        headers=portal.shop.headers,
    )
    assert unrepaired.status_code == 204, unrepaired.text
    assert (await deliver(client, portal.shop, order["id"])).status_code == 204
    found = await detail(client, portal.maria, order["id"])
    assert found["documents"]["delivery_summary"] is True
    assert found["warranty"] is None
    assert "no hay garantía" in text_of(
        await summary(client, portal.maria, order["id"])
    )


# --- Límite ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_documents_share_the_portal_pdf_limit(
    client: AsyncClient, portal: Portal, limiter: Any
) -> None:
    order = await signed_order(client, portal)
    for _ in range(20):
        assert (await client_pdf(client, portal.maria, str(uuid4()))).status_code == 404
    assert (await sheet(client, portal.maria, order["id"])).status_code == 429
    assert (await summary(client, portal.maria, order["id"])).status_code == 429
