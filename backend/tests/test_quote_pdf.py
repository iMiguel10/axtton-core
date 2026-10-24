"""PDF del presupuesto (A9, A14, RF-37 y RF-55 en su versión F0)."""

from collections.abc import AsyncIterator
from io import BytesIO
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pypdf import PdfReader

from app.core import db
from app.main import app
from tests.conftest import TwoWorkshops


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http
    await db.engine.dispose()


async def create_quote(
    client: AsyncClient, two_workshops: TwoWorkshops, description: str
) -> str:
    created = await client.post(
        f"/api/v1/workshop/work-orders/{two_workshops.order_a}/quotes",
        json={"description": description, "quantity": "1", "unit_price_cents": 8550},
        headers={"X-Workshop-Id": str(two_workshops.a)},
    )
    quote_id: str = created.json()["quote_id"]
    return quote_id


async def send(client: AsyncClient, two_workshops: TwoWorkshops, quote_id: str) -> str:
    sent = await client.post(
        f"/api/v1/workshop/quotes/{quote_id}/send",
        headers={"X-Workshop-Id": str(two_workshops.a)},
    )
    # La página del portal (/portal/quotes/…) llama a la API en /api/v1/portal/quotes/….
    return "/api/v1" + urlparse(sent.json()["approval_url"]).path


def pdf_text(content: bytes) -> str:
    return "".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)


@pytest.mark.asyncio
async def test_workshop_and_portal_get_the_same_pdf_with_the_frozen_total(
    client: AsyncClient, two_workshops: TwoWorkshops
) -> None:
    quote_id = await create_quote(client, two_workshops, "Cambio de pastillas")
    link = await send(client, two_workshops, quote_id)

    from_workshop = await client.get(
        f"/api/v1/workshop/quotes/{quote_id}/pdf",
        headers={"X-Workshop-Id": str(two_workshops.a)},
    )
    from_portal = await client.get(f"{link}/pdf")

    assert from_workshop.headers["content-type"] == "application/pdf"
    assert from_workshop.headers["cache-control"] == "no-store"
    assert from_workshop.content.startswith(b"%PDF")
    # RF-55: el mismo documento, generado dos veces, sale idéntico.
    assert from_workshop.content == from_portal.content
    text = pdf_text(from_workshop.content)
    assert "103,46 €" in text
    assert "Taller A" in text and "Cliente A" in text


@pytest.mark.asyncio
async def test_a_draft_has_no_pdf(
    client: AsyncClient, two_workshops: TwoWorkshops
) -> None:
    quote_id = await create_quote(client, two_workshops, "Borrador")
    response = await client.get(
        f"/api/v1/workshop/quotes/{quote_id}/pdf",
        headers={"X-Workshop-Id": str(two_workshops.a)},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_another_workshop_cannot_download_the_pdf(
    client: AsyncClient, two_workshops: TwoWorkshops
) -> None:
    quote_id = await create_quote(client, two_workshops, "Cambio de pastillas")
    await send(client, two_workshops, quote_id)
    response = await client.get(
        f"/api/v1/workshop/quotes/{quote_id}/pdf",
        headers={"X-Workshop-Id": str(two_workshops.b)},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_html_in_a_description_is_printed_as_text_not_executed(
    client: AsyncClient, two_workshops: TwoWorkshops
) -> None:
    """Jinja escapa el HTML; y aunque no lo hiciera, el fetcher no cargaría la URL."""
    malicious = 'Aceite <img src="http://169.254.169.254/latest/meta-data">'
    quote_id = await create_quote(client, two_workshops, malicious)
    await send(client, two_workshops, quote_id)
    response = await client.get(
        f"/api/v1/workshop/quotes/{quote_id}/pdf",
        headers={"X-Workshop-Id": str(two_workshops.a)},
    )
    assert response.status_code == 200
    assert "<img" in pdf_text(response.content)
