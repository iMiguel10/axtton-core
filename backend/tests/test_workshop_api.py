"""La API del taller solo devuelve datos del taller de la cabecera."""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core import db
from app.main import app
from tests.conftest import TwoWorkshops


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http
    # El engine de la aplicación es global: sus conexiones quedan ligadas al
    # event loop de esta prueba y la siguiente usa otro. Se cierran aquí.
    await db.engine.dispose()


@pytest.mark.asyncio
async def test_each_workshop_sees_only_its_clients(
    client: AsyncClient, two_workshops: TwoWorkshops
) -> None:
    response_a = await client.get(
        "/api/v1/workshop/clients", headers={"X-Workshop-Id": str(two_workshops.a)}
    )
    response_b = await client.get(
        "/api/v1/workshop/clients", headers={"X-Workshop-Id": str(two_workshops.b)}
    )
    assert response_a.json() == ["Cliente A"]
    assert response_b.json() == ["Cliente B"]


@pytest.mark.asyncio
async def test_without_workshop_header_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/workshop/clients")
    assert response.status_code == 422
