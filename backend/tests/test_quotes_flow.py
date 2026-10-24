"""Flujo de F0 de punta a punta: borrador → envío → enlace → decisión.

Y las defensas de la base de datos sobre lo que tiene valor de prueba (RNF-11, RNF-12).
"""

import asyncio
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import db
from app.main import app
from tests.conftest import Engines, TwoWorkshops

LINE = {
    "description": "Cambio de pastillas de freno delanteras",
    "quantity": "1",
    "unit_price_cents": 8550,
    "vat_bp": 2100,
}


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http
    await db.engine.dispose()


async def create_and_send(
    client: AsyncClient, workshop_id: object, work_order_id: object
) -> tuple[str, str]:
    """Devuelve (quote_id, ruta del enlace de aprobación)."""
    headers = {"X-Workshop-Id": str(workshop_id)}
    created = await client.post(
        f"/api/v1/workshop/work-orders/{work_order_id}/quotes",
        json=LINE,
        headers=headers,
    )
    assert created.status_code == 201
    quote_id = created.json()["quote_id"]
    sent = await client.post(
        f"/api/v1/workshop/quotes/{quote_id}/send", headers=headers
    )
    assert sent.status_code == 200
    assert sent.json()["total_cents"] == 10346
    return quote_id, urlparse(sent.json()["approval_url"]).path


async def work_order_status(engines: Engines, work_order_id: object) -> str | None:
    async with engines.platform.connect() as conn:
        return await conn.scalar(
            text("SELECT status FROM work_orders WHERE id = :id"), {"id": work_order_id}
        )


@pytest.mark.asyncio
async def test_approving_through_the_link_moves_the_work_order(
    client: AsyncClient, engines: Engines, two_workshops: TwoWorkshops
) -> None:
    _, link = await create_and_send(client, two_workshops.a, two_workshops.order_a)
    assert (
        await work_order_status(engines, two_workshops.order_a)
        == "pendiente_aprobacion"
    )

    view = await client.get(link)
    assert view.json()["status"] == "sent"

    decided = await client.post(f"{link}/decision", json={"outcome": "approved"})
    assert decided.status_code == 204
    assert await work_order_status(engines, two_workshops.order_a) == "aprobada"


@pytest.mark.asyncio
async def test_rejecting_sends_the_work_order_back_to_diagnosis(
    client: AsyncClient, engines: Engines, two_workshops: TwoWorkshops
) -> None:
    _, link = await create_and_send(client, two_workshops.a, two_workshops.order_a)
    await client.post(f"{link}/decision", json={"outcome": "rejected"})
    assert await work_order_status(engines, two_workshops.order_a) == "en_diagnostico"


@pytest.mark.asyncio
async def test_a_quote_cannot_be_sent_twice(
    client: AsyncClient, two_workshops: TwoWorkshops
) -> None:
    quote_id, _ = await create_and_send(client, two_workshops.a, two_workshops.order_a)
    again = await client.post(
        f"/api/v1/workshop/quotes/{quote_id}/send",
        headers={"X-Workshop-Id": str(two_workshops.a)},
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_a_decided_quote_cannot_be_decided_again(
    client: AsyncClient, two_workshops: TwoWorkshops
) -> None:
    _, link = await create_and_send(client, two_workshops.a, two_workshops.order_a)
    await client.post(f"{link}/decision", json={"outcome": "approved"})
    again = await client.post(f"{link}/decision", json={"outcome": "rejected"})
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_link_with_another_workshop_in_the_url_finds_nothing(
    client: AsyncClient, two_workshops: TwoWorkshops
) -> None:
    _, link = await create_and_send(client, two_workshops.a, two_workshops.order_a)
    tampered = link.replace(str(two_workshops.a), str(two_workshops.b))
    assert (await client.get(tampered)).status_code == 404
    decided = await client.post(f"{tampered}/decision", json={"outcome": "approved"})
    assert decided.status_code == 404


@pytest.mark.asyncio
async def test_invented_token_finds_nothing(
    client: AsyncClient, two_workshops: TwoWorkshops
) -> None:
    response = await client.get(f"/api/v1/portal/quotes/{two_workshops.a}/inventado")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_workshop_b_cannot_send_a_quote_of_workshop_a(
    client: AsyncClient, two_workshops: TwoWorkshops
) -> None:
    created = await client.post(
        f"/api/v1/workshop/work-orders/{two_workshops.order_a}/quotes",
        json=LINE,
        headers={"X-Workshop-Id": str(two_workshops.a)},
    )
    quote_id = created.json()["quote_id"]
    sent_by_b = await client.post(
        f"/api/v1/workshop/quotes/{quote_id}/send",
        headers={"X-Workshop-Id": str(two_workshops.b)},
    )
    assert sent_by_b.status_code == 404


@pytest.mark.asyncio
async def test_two_simultaneous_sends_leave_a_single_sent_quote(
    client: AsyncClient, engines: Engines, two_workshops: TwoWorkshops
) -> None:
    """La carrera de §7.1: dos envíos a la vez del mismo presupuesto."""
    headers = {"X-Workshop-Id": str(two_workshops.a)}
    created = await client.post(
        f"/api/v1/workshop/work-orders/{two_workshops.order_a}/quotes",
        json=LINE,
        headers=headers,
    )
    quote_id = created.json()["quote_id"]
    results = await asyncio.gather(
        client.post(f"/api/v1/workshop/quotes/{quote_id}/send", headers=headers),
        client.post(f"/api/v1/workshop/quotes/{quote_id}/send", headers=headers),
    )
    assert sorted(r.status_code for r in results) == [200, 409]


# --- Defensas de la base de datos: aunque la aplicación tuviera un fallo ---


async def sent_quote_id(client: AsyncClient, two_workshops: TwoWorkshops) -> str:
    quote_id, link = await create_and_send(
        client, two_workshops.a, two_workshops.order_a
    )
    await client.post(f"{link}/decision", json={"outcome": "approved"})
    return quote_id


@pytest.mark.asyncio
async def test_lines_of_a_sent_quote_cannot_change(
    client: AsyncClient, engines: Engines, two_workshops: TwoWorkshops
) -> None:
    quote_id = await sent_quote_id(client, two_workshops)
    async with engines.platform.begin() as conn:
        with pytest.raises(DBAPIError, match="lines are frozen"):
            await conn.execute(
                text("UPDATE quote_lines SET unit_price_cents = 1 WHERE quote_id = :q"),
                {"q": quote_id},
            )


@pytest.mark.asyncio
async def test_total_of_a_sent_quote_cannot_change(
    client: AsyncClient, engines: Engines, two_workshops: TwoWorkshops
) -> None:
    quote_id = await sent_quote_id(client, two_workshops)
    async with engines.platform.begin() as conn:
        with pytest.raises(DBAPIError, match="cannot change"):
            await conn.execute(
                text("UPDATE quotes SET total_cents = 1 WHERE id = :q"), {"q": quote_id}
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    ["UPDATE quote_decisions SET outcome = 'rejected'", "DELETE FROM quote_decisions"],
)
async def test_r5_decisions_cannot_be_updated_or_deleted(
    client: AsyncClient, engines: Engines, two_workshops: TwoWorkshops, statement: str
) -> None:
    await sent_quote_id(client, two_workshops)
    # Ni siquiera el rol de plataforma, que se salta RLS.
    async with engines.platform.begin() as conn:
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text(statement))


@pytest.mark.asyncio
async def test_only_the_token_hash_is_stored(
    client: AsyncClient, engines: Engines, two_workshops: TwoWorkshops
) -> None:
    _, link = await create_and_send(client, two_workshops.a, two_workshops.order_a)
    token = link.rsplit("/", 1)[1]
    async with engines.platform.connect() as conn:
        stored = await conn.scalar(text("SELECT approval_token_hash FROM quotes"))
    # Lo guardado es el sha256 (32 bytes), no el token en claro.
    assert stored is not None and len(bytes(stored)) == 32
    assert token.encode() not in bytes(stored)
