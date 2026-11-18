"""El PDF de la hoja de recepción (F6 paso 3: RF-51, RF-52, RF-55, RF-15).

Se lee su texto con pypdf, como el del presupuesto: lo que importa es lo que
pone. Y, firmada, que salga idéntica byte a byte aunque se corrija la recepción.
"""

import io
import re

import pytest
from httpx import AsyncClient, Response
from pypdf import PdfReader

from app.infra.email import InMemoryEmailSender
from tests.test_anonymize import anonymize, read
from tests.test_clients import open_workshop
from tests.test_employees import add_mechanic, invite_and_accept
from tests.test_quote_pdf import text_of
from tests.test_reception import RECEPTION, sign, sign_on_screen
from tests.test_work_orders import (
    URL,
    Shop,
    force_status,
    get,
    open_order,
    outbox,
    shop,
)

__all__ = ["outbox", "shop"]


async def pdf(client: AsyncClient, headers: dict[str, str], order_id: str) -> Response:
    return await client.get(f"{URL}/{order_id}/reception-sheet/pdf", headers=headers)


def line_segments(response: Response) -> int:
    """Los segmentos de recta que dibuja la página (el operador `l` de PDF).
    WeasyPrint dibuja el SVG de la firma como trazos dentro de la página, no
    como una imagen aparte: cada punto de un trazo es un segmento."""
    (page, *_) = PdfReader(io.BytesIO(response.content)).pages
    contents = page.get_contents()
    assert contents is not None
    return len(re.findall(rb"[\d.]+ [\d.]+ l\n", contents.get_data()))


@pytest.mark.asyncio
async def test_an_unsigned_sheet_has_the_reception_of_the_order(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"], **RECEPTION)
    response = await pdf(client, shop.headers, order["id"])
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    content = text_of(response)
    for expected in (
        "Hoja de recepción",
        "Resguardo de depósito",
        order["code"],
        "Sin firmar",
        "María",
        "Jaime Sánchez · 688 777 666",
        shop.car["plate"],
        "123.456 km",
        "1/4",
        "Ruido al frenar",
        "Rayón en la puerta trasera",
        "Silla infantil",
        # La renuncia expresa (RF-51), con sus palabras.
        "Renuncio al presupuesto.",
        # Sin firmar, el hueco para firmarla en papel.
        "Firma y nombre",
    ):
        assert expected in content, expected


@pytest.mark.asyncio
async def test_a_sheet_signed_on_screen_carries_the_signature(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"], **RECEPTION)
    unsigned = await pdf(client, shop.headers, order["id"])
    assert (await sign_on_screen(client, shop.headers, order)).status_code == 204
    signed = await pdf(client, shop.headers, order["id"])
    content = text_of(signed)
    assert "Firmada por el cliente en pantalla" in content
    assert "Firmada en pantalla por Jaime Sánchez el" in content
    assert "Recogida en el taller por Ana López" in content
    assert "Firma y nombre" not in content
    # La firma está dibujada (el SVG que escribe el servidor): sus trazos tienen
    # tres segmentos (dos y uno), que sin firmar no están.
    assert line_segments(signed) - line_segments(unsigned) >= 3


@pytest.mark.asyncio
async def test_a_sheet_signed_on_paper_says_so(client: AsyncClient, shop: Shop) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    assert (await sign(client, shop.headers, order)).status_code == 204
    response = await pdf(client, shop.headers, order["id"])
    content = text_of(response)
    assert "Firmada en papel y conforme el" in content
    assert "El taller conserva la copia firmada" in content
    assert "Renuncio al presupuesto" not in content


@pytest.mark.asyncio
async def test_rf55_a_signed_sheet_comes_out_identical_after_a_correction(
    client: AsyncClient, shop: Shop
) -> None:
    """Corregir la recepción después de firmar cambia la orden, no la hoja: el
    PDF sale byte a byte igual, desde su copia congelada."""
    order = await open_order(client, shop.headers, shop.car["id"], **RECEPTION)
    assert (await sign_on_screen(client, shop.headers, order)).status_code == 204
    first = await pdf(client, shop.headers, order["id"])
    signed = await get(client, shop.headers, order["id"])
    corrected = await client.patch(
        f"{URL}/{order['id']}",
        json={
            "version": signed["version"],
            "odometer_km": 999,
            "belongings": "Nada",
            "dropped_off_by_name": "Otra persona",
            "quote_waived": False,
        },
        headers=shop.headers,
    )
    assert corrected.status_code == 204
    again = await pdf(client, shop.headers, order["id"])
    assert again.content == first.content
    content = text_of(again)
    assert "123.456 km" in content
    assert "Otra persona" not in content


@pytest.mark.asyncio
async def test_the_client_name_disappears_when_anonymized(
    client: AsyncClient, shop: Shop
) -> None:
    """RF-15: el nombre del cliente se lee al generarla, y quién trajo el coche
    y quién firmó se vacían en la hoja firmada."""
    order = await open_order(client, shop.headers, shop.car["id"], **RECEPTION)
    assert (await sign_on_screen(client, shop.headers, order)).status_code == 204
    await force_status(order["id"], "delivered")
    maria = await read(client, shop.headers, shop.maria["id"])
    assert (await anonymize(client, shop.headers, maria)).status_code == 204

    content = text_of(await pdf(client, shop.headers, order["id"]))
    assert "Cliente eliminado" in content
    assert "María" not in content
    assert "Jaime" not in content
    assert "688" not in content
    # Lo demás de la hoja, y la firma hasta su plazo (RF-56), se queda.
    assert "Rayón en la puerta trasera" in content
    assert "Firmada en pantalla el" in content


@pytest.mark.asyncio
async def test_only_the_admin_generates_it(
    client: AsyncClient, shop: Shop, outbox: InMemoryEmailSender
) -> None:
    juan = await add_mechanic(client, shop.admin, "Juan")
    mechanic = await invite_and_accept(client, shop.admin, outbox, juan)
    order = await open_order(client, shop.headers, shop.car["id"])
    assert (await pdf(client, mechanic, order["id"])).status_code == 403


@pytest.mark.asyncio
async def test_the_sheet_of_another_workshop_does_not_exist(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    other = (await open_workshop(client, "Taller B")).headers
    response = await pdf(client, other, order["id"])
    assert response.status_code == 404
    assert response.json()["code"] == "work_order_not_found"
