"""El PDF del presupuesto (F3 paso 7: RF-37, RF-38, RF-55, A14).

Se lee su texto con pypdf: lo que importa es lo que pone, no cómo se dibuja.
"""

import io
from typing import Any

import pytest
from httpx import AsyncClient, Response
from pypdf import PdfReader

from app.infra.email import InMemoryEmailSender
from tests.test_clients import open_workshop
from tests.test_employees import add_mechanic, invite_and_accept
from tests.test_quote_decision import decide
from tests.test_quote_send import order_of, send, version_of
from tests.test_quotes import ORDERS, QUOTES, create, quotes_of, save
from tests.test_settings import LOGO, SETTINGS, image
from tests.test_work_orders import Shop, open_order, outbox, shop

__all__ = ["outbox", "shop"]

BRAKES = {
    "kind": "part",
    "description": "Pastillas de freno delanteras",
    "reference": "BP-1234",
    "part_condition": "reconditioned",
    "quantity": "1",
    "unit_price_cents": 10000,
    "vat_bp": 2100,
}
LABOR = {
    "kind": "labor",
    "description": "Cambio de pastillas",
    "quantity": "1.5",
    "unit_price_cents": 4000,
    "vat_bp": 2100,
}


async def legal_data(client: AsyncClient, shop: Shop, **fields: Any) -> None:
    current = await client.get(SETTINGS, headers=shop.headers)
    response = await client.patch(
        SETTINGS,
        json={"version": current.json()["version"], **fields},
        headers=shop.headers,
    )
    assert response.status_code == 204, response.text


async def diagnosing_order_with_km(client: AsyncClient, shop: Shop) -> str:
    order = await open_order(client, shop.headers, shop.car["id"], odometer_km=187410)
    moved = await client.post(
        f"{ORDERS}/{order['id']}/status",
        json={"version": order["version"], "to_status": "diagnosing"},
        headers=shop.headers,
    )
    assert moved.status_code == 204, moved.text
    order_id: str = order["id"]
    return order_id


async def draft(
    client: AsyncClient, shop: Shop, order_id: str, delivery: int | None = 3
) -> str:
    quote_id = await create(client, shop.headers, order_id)
    saved = await save(
        client,
        shop.headers,
        quote_id,
        1,
        [BRAKES, LABOR],
        global_discount={"kind": "percent", "value": 1000},
        delivery_business_days=delivery,
    )
    assert saved.status_code == 200, saved.text
    return quote_id


async def pdf(client: AsyncClient, headers: dict[str, str], quote_id: str) -> Response:
    return await client.get(f"{QUOTES}/{quote_id}/pdf", headers=headers)


def text_of(response: Response) -> str:
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF")
    reader = PdfReader(io.BytesIO(response.content))
    # Sin saltos de línea ni espacios dobles: lo que se busca puede partirse.
    return " ".join(" ".join(page.extract_text() for page in reader.pages).split())


@pytest.mark.asyncio
async def test_a_sent_version_has_what_the_regulation_requires(
    client: AsyncClient, shop: Shop
) -> None:
    """RF-37: el taller (nombre, NIF, domicilio, registro industrial), el
    vehículo (marca, modelo, matrícula y km), las líneas con sus importes, la
    fecha, la validez y el plazo de entrega."""
    await legal_data(
        client,
        shop,
        legal_name="Talleres Pérez S. L.",
        tax_id="B12345678",
        address="Calle Mayor 1, 28013 Madrid",
        industrial_registry_number="28-123456",
    )
    order_id = await diagnosing_order_with_km(client, shop)
    quote_id = await draft(client, shop, order_id)
    assert (await send(client, shop, order_id, quote_id)).status_code == 204

    response = await pdf(client, shop.headers, quote_id)
    order = await order_of(client, shop, order_id)
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-disposition"] == (
        f'inline; filename="presupuesto-{order["code"]}-v1.pdf"'
    )
    content = text_of(response)
    for expected in (
        "Talleres Pérez S. L.",
        "NIF B12345678",
        "Calle Mayor 1, 28013 Madrid",
        "Registro industrial n.º 28-123456",
        "María",
        shop.car["plate"],
        "Seat",
        "187.410 km",
        f"{order['code']} · versión 1",
        "Pendiente de la decisión del cliente",
        "Hasta el",
        "3 días hábiles desde la aceptación",
        "Pastillas de freno delanteras",
        "Ref. BP-1234",
        # RF-38: la pieza reacondicionada se marca, con su aviso de conformidad.
        "Pieza reacondicionada",
        "necesitan la conformidad del cliente",
        # 100 € + 1,5 h × 40 € = 160 €; el 10 % global, como tal (RF-39).
        "160,00 €",
        "Descuento (10 %)",
        "−16,00 €",
        "Total, IVA incluido",
        "174,24 €",
    ):
        assert expected in content, expected
    assert "BORRADOR" not in content


@pytest.mark.asyncio
async def test_rf55_the_same_version_comes_out_identical_until_the_client_decides(
    client: AsyncClient, shop: Shop
) -> None:
    """Corregir la ficha del vehículo después de enviar no cambia lo que se
    presupuestó; decidir sí cambia el PDF (lleva la decisión), y desde ahí
    vuelve a salir siempre igual."""
    order_id = await diagnosing_order_with_km(client, shop)
    quote_id = await draft(client, shop, order_id)
    assert (await send(client, shop, order_id, quote_id)).status_code == 204
    first = await pdf(client, shop.headers, quote_id)

    vehicle = await client.get(
        f"/api/v1/workshop/vehicles/{shop.car['id']}", headers=shop.headers
    )
    edited = await client.patch(
        f"/api/v1/workshop/vehicles/{shop.car['id']}",
        json={"version": vehicle.json()["version"], "make": "Cupra"},
        headers=shop.headers,
    )
    assert edited.status_code == 204, edited.text
    again = await pdf(client, shop.headers, quote_id)
    assert again.content == first.content
    assert "Cupra" not in text_of(again)

    assert (await decide(client, shop, order_id, quote_id)).status_code == 204
    decided = await pdf(client, shop.headers, quote_id)
    assert decided.content != first.content
    content = text_of(decided)
    assert "Aceptado por el cliente" in content
    assert "por teléfono" in content
    assert "Decisión registrada por" in content
    (quote,) = await quotes_of(client, shop.headers, order_id)
    day, month, year = reversed(quote["delivery_on"].split("-"))
    assert f"{day}/{month}/{year}" in content
    assert (await pdf(client, shop.headers, quote_id)).content == decided.content


@pytest.mark.asyncio
async def test_a_draft_preview_says_it_is_not_valid_and_what_data_is_missing(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await diagnosing_order_with_km(client, shop)
    quote_id = await draft(client, shop, order_id, delivery=None)

    response = await pdf(client, shop.headers, quote_id)
    order = await order_of(client, shop, order_id)
    assert response.headers["content-disposition"] == (
        f'inline; filename="borrador-{order["code"]}-v1.pdf"'
    )
    content = text_of(response)
    # La marca de agua, girada: pypdf la lee sin algún espacio.
    assert "BORRADOR" in content
    assert "Borrador, no válido" in content
    # El taller recién creado no tiene sus datos legales.
    assert "el NIF" in content
    assert "el número de registro industrial" in content
    assert "Sin enviar" in content
    assert "Sin indicar" in content
    # Los totales de un borrador se calculan al pedirlo.
    assert "174,24 €" in content


@pytest.mark.asyncio
async def test_the_logo_of_the_workshop_goes_in_the_pdf(
    client: AsyncClient, shop: Shop
) -> None:
    uploaded = await client.put(
        LOGO,
        content=image("PNG"),
        headers={**shop.headers, "Content-Type": "image/png"},
    )
    assert uploaded.status_code == 204, uploaded.text
    order_id = await diagnosing_order_with_km(client, shop)
    quote_id = await draft(client, shop, order_id)

    response = await pdf(client, shop.headers, quote_id)
    assert response.status_code == 200
    (page, *_) = PdfReader(io.BytesIO(response.content)).pages
    assert len(page.images) == 1


@pytest.mark.asyncio
async def test_a_quote_without_its_delivery_term_is_not_sent(
    client: AsyncClient, shop: Shop
) -> None:
    """RF-37: sin la fecha prevista de entrega no hay presupuesto válido. Al
    corregir, la versión nueva copia el plazo de la anterior."""
    order_id = await diagnosing_order_with_km(client, shop)
    quote_id = await draft(client, shop, order_id, delivery=None)
    refused = await send(client, shop, order_id, quote_id)
    assert refused.status_code == 409
    assert refused.json()["code"] == "quote_delivery_missing"

    version = await version_of(client, shop, order_id, quote_id)
    await save(
        client, shop.headers, quote_id, version, [LABOR], delivery_business_days=7
    )
    assert (await send(client, shop, order_id, quote_id)).status_code == 204
    corrected = await create(client, shop.headers, order_id)
    latest = next(
        q
        for q in await quotes_of(client, shop.headers, order_id)
        if q["id"] == corrected
    )
    assert latest["delivery_business_days"] == 7
    assert latest["delivery_on"] is None


@pytest.mark.asyncio
async def test_an_invalid_delivery_term_is_a_422(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await diagnosing_order_with_km(client, shop)
    quote_id = await create(client, shop.headers, order_id)
    for days in (0, 251):
        response = await save(
            client, shop.headers, quote_id, 1, [LABOR], delivery_business_days=days
        )
        assert response.status_code == 422, days


@pytest.mark.asyncio
async def test_a_mechanic_who_cannot_see_prices_gets_no_pdf(
    client: AsyncClient, shop: Shop, outbox: InMemoryEmailSender
) -> None:
    mechanic = await invite_and_accept(
        client, shop.admin, outbox, await add_mechanic(client, shop.admin)
    )
    order_id = await diagnosing_order_with_km(client, shop)
    quote_id = await draft(client, shop, order_id)
    assert (await pdf(client, mechanic, quote_id)).status_code == 200

    await legal_data(client, shop, mechanics_see_sale_prices=False)
    refused = await pdf(client, mechanic, quote_id)
    assert refused.status_code == 403
    assert refused.json()["code"] == "quote_prices_hidden"


@pytest.mark.asyncio
async def test_an_unknown_quote_has_no_pdf(client: AsyncClient, shop: Shop) -> None:
    response = await pdf(client, shop.headers, "00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["code"] == "quote_not_found"


@pytest.mark.asyncio
async def test_rnf01_the_pdf_of_another_workshop_does_not_exist(
    client: AsyncClient, shop: Shop
) -> None:
    """Bajo RLS, la versión de otro taller no existe: 404, no 403 (RNF-01)."""
    order_id = await diagnosing_order_with_km(client, shop)
    quote_id = await draft(client, shop, order_id)
    other = (await open_workshop(client, "Taller B")).headers
    response = await pdf(client, other, quote_id)
    assert response.status_code == 404
    assert response.json()["code"] == "quote_not_found"


@pytest.mark.asyncio
async def test_a_new_quote_starts_with_the_default_delivery_term_of_the_workshop(
    client: AsyncClient, shop: Shop
) -> None:
    """RF-02: el administrador fija un plazo por defecto. El primer presupuesto
    de una orden empieza con él; quitarlo deja el borrador sin plazo."""
    await legal_data(client, shop, default_delivery_business_days=6)
    settings = await client.get(SETTINGS, headers=shop.headers)
    assert settings.json()["default_delivery_business_days"] == 6

    order_id = await diagnosing_order_with_km(client, shop)
    await create(client, shop.headers, order_id)
    (first,) = await quotes_of(client, shop.headers, order_id)
    assert first["delivery_business_days"] == 6

    await legal_data(client, shop, default_delivery_business_days=None)
    other = await diagnosing_order_with_km(client, shop)
    await create(client, shop.headers, other)
    (second,) = await quotes_of(client, shop.headers, other)
    assert second["delivery_business_days"] is None

    for days in (0, 251):
        current = await client.get(SETTINGS, headers=shop.headers)
        refused = await client.patch(
            SETTINGS,
            json={
                "version": current.json()["version"],
                "default_delivery_business_days": days,
            },
            headers=shop.headers,
        )
        assert refused.status_code == 422, days
