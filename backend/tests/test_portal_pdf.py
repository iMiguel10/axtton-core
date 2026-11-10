"""El PDF de cada versión para el cliente (F4 paso 6: RF-54, RF-55, T4).

El mismo documento que el del taller, sin lo que el portal tampoco enseña: el
motivo de una anulación y quién del taller anotó la decisión. Y solo de lo suyo.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response

from app.infra.email import InMemoryEmailSender
from app.infra.rate_limit import (
    LimitsRateLimiter,
    current_rate_limiter,
    set_rate_limiter,
)
from tests.test_clients import create as create_client
from tests.test_clients import open_workshop
from tests.test_portal_decision import luis_sent_quote, post_decision
from tests.test_portal_orders import PORTAL, Portal, enter, portal
from tests.test_quote_decision import decide, sent_order
from tests.test_quote_pdf import diagnosing_order_with_km, draft, legal_data, text_of
from tests.test_quote_pdf import pdf as workshop_pdf
from tests.test_quote_send import cancel, diagnosing_order, draft_with_lines, send
from tests.test_quotes import create
from tests.test_vehicles import create as create_vehicle
from tests.test_work_orders import outbox

__all__ = ["outbox", "portal"]

CANCEL_REASON = "El cliente es un pesado, mejor no insistir"


async def client_pdf(
    client: AsyncClient, headers: dict[str, str], quote_id: str
) -> Response:
    return await client.get(f"{PORTAL}/quotes/{quote_id}/pdf", headers=headers)


async def sent_with_legal_data(client: AsyncClient, portal: Portal) -> tuple[str, str]:
    await legal_data(
        client,
        portal.shop,
        legal_name="Talleres Pérez S. L.",
        tax_id="B12345678",
        address="Calle Mayor 1, 28013 Madrid",
        industrial_registry_number="28-123456",
    )
    order_id = await diagnosing_order_with_km(client, portal.shop)
    quote_id = await draft(client, portal.shop, order_id)
    assert (await send(client, portal.shop, order_id, quote_id)).status_code == 204
    return order_id, quote_id


# --- Lo que descarga --------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_client_downloads_the_same_document_as_the_workshop(
    client: AsyncClient, portal: Portal
) -> None:
    """Sin nada que ocultar (una versión pendiente), byte a byte el del taller: lo
    que exige RF-37 llega entero al cliente."""
    _, quote_id = await sent_with_legal_data(client, portal)

    response = await client_pdf(client, portal.maria, quote_id)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-disposition"].startswith(
        'inline; filename="presupuesto-OT-'
    )
    content = text_of(response)
    for expected in (
        "Talleres Pérez S. L.",
        "NIF B12345678",
        "Registro industrial n.º 28-123456",
        "187.410 km",
        "Pendiente de la decisión del cliente",
        "Pieza reacondicionada",
        "3 días hábiles desde la aceptación",
    ):
        assert expected in content, expected
    workshop = await workshop_pdf(client, portal.shop.headers, quote_id)
    assert response.content == workshop.content


@pytest.mark.asyncio
async def test_rf55_it_comes_out_identical_while_nothing_changes(
    client: AsyncClient, portal: Portal
) -> None:
    _, quote_id = await sent_with_legal_data(client, portal)
    first = await client_pdf(client, portal.maria, quote_id)
    again = await client_pdf(client, portal.maria, quote_id)
    assert first.status_code == again.status_code == 200
    assert first.content == again.content


@pytest.mark.asyncio
async def test_it_does_not_say_who_in_the_workshop_recorded_the_decision(
    client: AsyncClient, portal: Portal
) -> None:
    """Sí cuándo y por dónde aceptó, que es lo que pide RF-37."""
    order_id, quote_id = await sent_order(client, portal.shop)
    assert (await decide(client, portal.shop, order_id, quote_id)).status_code == 204

    theirs = text_of(await workshop_pdf(client, portal.shop.headers, quote_id))
    mine = text_of(await client_pdf(client, portal.maria, quote_id))
    assert "Decisión registrada por" in theirs
    assert "Decisión registrada por" not in mine
    assert "Ana López" not in mine
    assert "Aceptado por el cliente" in mine
    assert "por teléfono" in mine


@pytest.mark.asyncio
async def test_a_decision_in_the_portal_says_so(
    client: AsyncClient, portal: Portal
) -> None:
    _, quote_id = await sent_order(client, portal.shop)
    assert (await post_decision(client, portal.maria, quote_id)).status_code == 204
    content = text_of(await client_pdf(client, portal.maria, quote_id))
    assert "Aceptado por el cliente" in content
    assert "en el portal del cliente" in content


@pytest.mark.asyncio
async def test_a_cancelled_version_says_so_without_the_reason(
    client: AsyncClient, portal: Portal
) -> None:
    order_id, quote_id = await sent_order(client, portal.shop)
    cancelled = await cancel(client, portal.shop, order_id, quote_id, CANCEL_REASON)
    assert cancelled.status_code == 204, cancelled.text

    theirs = text_of(await workshop_pdf(client, portal.shop.headers, quote_id))
    mine = text_of(await client_pdf(client, portal.maria, quote_id))
    assert CANCEL_REASON in theirs
    assert "Anulado por el taller" in mine
    assert CANCEL_REASON not in mine
    assert "Motivo de la anulación" not in mine


@pytest.mark.asyncio
async def test_every_sent_version_can_be_downloaded(
    client: AsyncClient, portal: Portal
) -> None:
    """RF-54: también la que el taller sustituyó."""
    order_id, first = await sent_order(client, portal.shop)
    second = await create(client, portal.shop.headers, order_id)
    assert (await send(client, portal.shop, order_id, second)).status_code == 204

    old = text_of(await client_pdf(client, portal.maria, first))
    assert "Sustituido por una versión posterior" in old
    assert "versión 1" in old
    assert "versión 2" in text_of(await client_pdf(client, portal.maria, second))


# --- T4: solo lo suyo ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_t4_a_quote_of_another_client_does_not_exist(
    client: AsyncClient, portal: Portal
) -> None:
    _, theirs = await luis_sent_quote(client, portal.shop)
    response = await client_pdf(client, portal.maria, theirs)
    missing = await client_pdf(client, portal.maria, str(uuid4()))
    assert response.status_code == missing.status_code == 404
    assert response.json() == missing.json()
    # Luis sí: la prueba no pasa porque nadie pueda descargarlo.
    assert (await client_pdf(client, portal.luis, theirs)).status_code == 200


@pytest.mark.asyncio
async def test_t4_nor_one_of_the_same_email_in_another_workshop(
    client: AsyncClient, outbox: InMemoryEmailSender, portal: Portal
) -> None:
    _, quote_id = await sent_order(client, portal.shop)
    other = await open_workshop(client, "Taller B")
    same = await create_client(
        client, other.headers, name="María", email="m@example.com"
    )
    await create_vehicle(client, other.headers, same["id"], make="Opel")
    session_b = await enter(
        client, outbox, UUID(other.headers["X-Workshop-Id"]), "m@example.com"
    )
    assert (await client_pdf(client, session_b, quote_id)).status_code == 404


@pytest.mark.asyncio
async def test_a_draft_does_not_exist_for_the_client(
    client: AsyncClient, portal: Portal
) -> None:
    """La vista previa con marca de agua es solo del taller."""
    order_id = await diagnosing_order(client, portal.shop)
    quote_id = await draft_with_lines(client, portal.shop, order_id)
    response = await client_pdf(client, portal.maria, quote_id)
    assert (response.status_code, response.json()["code"]) == (404, "quote_not_found")


@pytest.mark.asyncio
async def test_only_a_client_session_downloads_it(
    client: AsyncClient, portal: Portal
) -> None:
    """Invariante 3, y ningún enlace público (RF-54)."""
    _, quote_id = await sent_order(client, portal.shop)
    assert (await client_pdf(client, portal.shop.headers, quote_id)).status_code == 403
    assert (await client_pdf(client, {}, quote_id)).status_code == 401


# --- Límite de peticiones -----------------------------------------------------------


@pytest_asyncio.fixture
async def limiter() -> AsyncIterator[None]:
    previous = current_rate_limiter()
    set_rate_limiter(LimitsRateLimiter("async+memory://"))
    yield
    set_rate_limiter(previous)


@pytest.mark.asyncio
async def test_a_client_cannot_keep_the_pdf_slots_busy(
    client: AsyncClient, portal: Portal, limiter: Any
) -> None:
    """Solo hay dos maquetaciones a la vez, compartidas con el taller. El límite
    va antes de buscar la versión, así que también cuentan las que no existen."""
    _, quote_id = await sent_order(client, portal.shop)
    for _ in range(20):
        assert (await client_pdf(client, portal.maria, str(uuid4()))).status_code == 404
    limited = await client_pdf(client, portal.maria, quote_id)
    assert (limited.status_code, limited.json()["code"]) == (429, "rate_limited")
    # Otro cliente del mismo taller, no: el límite es de cada uno.
    _, theirs = await luis_sent_quote(client, portal.shop)
    assert (await client_pdf(client, portal.luis, theirs)).status_code == 200
