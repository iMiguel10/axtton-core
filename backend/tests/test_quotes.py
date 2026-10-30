"""El borrador de un presupuesto por la API (F3 paso 4: RF-30 a RF-32, RF-38,
RF-39, RNF-15)."""

import asyncio
import os
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.errors import ConflictError
from app.infra.email import InMemoryEmailSender
from tests.conftest import Engines, TwoWorkshops
from tests.test_clients import open_workshop
from tests.test_concurrency import (
    GRACE,
    MakeAccount,
    dispose_global_engines,  # noqa: F401
    employee_with_access,
    finish,
    open_transaction,
)
from tests.test_employees import add_mechanic, invite_and_accept
from tests.test_quotes_db import SEND, calculate_lines
from tests.test_work_orders import Shop, force_status, open_order, outbox, shop
from tests.test_work_orders_db import seed_order

__all__ = ["outbox", "shop"]

ORDERS = "/api/v1/workshop/orders"
QUOTES = "/api/v1/workshop/quotes"

LABOR = {
    "kind": "labor",
    "description": "Mecánica",
    "quantity": "1.5",
    "unit_price_cents": 4500,
    "vat_bp": 2100,
}
PART = {
    "kind": "part",
    "description": "Pastillas de freno",
    "reference": "PF-123",
    "part_condition": "used",
    "quantity": "1",
    "unit_price_cents": 6000,
    "discount_bp": 1000,
    "vat_bp": 2100,
}


async def new_order(client: AsyncClient, shop: Shop) -> str:
    order = await open_order(client, shop.headers, shop.car["id"])
    order_id: str = order["id"]
    return order_id


async def create(client: AsyncClient, headers: dict[str, str], order_id: str) -> str:
    response = await client.post(f"{ORDERS}/{order_id}/quotes", headers=headers)
    assert response.status_code == 201, response.text
    quote_id: str = response.json()["id"]
    return quote_id


async def quotes_of(
    client: AsyncClient, headers: dict[str, str], order_id: str
) -> list[dict[str, Any]]:
    response = await client.get(f"{ORDERS}/{order_id}/quotes", headers=headers)
    assert response.status_code == 200, response.text
    result: list[dict[str, Any]] = response.json()
    return result


async def save(
    client: AsyncClient,
    headers: dict[str, str],
    quote_id: str,
    version: int,
    lines: list[dict[str, Any]],
    global_discount: dict[str, Any] | None = None,
) -> Any:
    return await client.put(
        f"{QUOTES}/{quote_id}",
        json={"version": version, "lines": lines, "global_discount": global_discount},
        headers=headers,
    )


async def send_by_sql(quote_id: str, employee_name: str = "Ana") -> None:
    """Envía una versión de una línea de 100 € + 21 % con el rol de plataforma,
    como lo hará el paso 5 (que todavía no existe)."""
    engine = create_async_engine(os.environ["PLATFORM_DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            employee = await conn.scalar(
                text("SELECT created_by_employee_id FROM quotes WHERE id = :q"),
                {"q": quote_id},
            )
            await calculate_lines(conn, UUID(quote_id))
            await conn.execute(text(SEND), {"q": quote_id, "e": employee, "t": 12100})
    finally:
        await engine.dispose()


ONE_HUNDRED = {
    "kind": "labor",
    "description": "Diagnóstico",
    "quantity": "1",
    "unit_price_cents": 10000,
    "vat_bp": 2100,
}


# --- Preparar el borrador (RF-30, RF-31) ----------------------------------------


@pytest.mark.asyncio
async def test_a_draft_is_created_empty_and_saved_with_its_totals_calculated(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await new_order(client, shop)
    quote_id = await create(client, shop.headers, order_id)
    (draft,) = await quotes_of(client, shop.headers, order_id)
    assert (draft["version_no"], draft["status"], draft["lines"]) == (1, "draft", [])
    assert draft["totals"]["total_cents"] == 0

    response = await save(
        client,
        shop.headers,
        quote_id,
        draft["version"],
        [LABOR, PART],
        {"kind": "amount", "value": 500},
    )
    assert response.status_code == 200, response.text
    (draft,) = await quotes_of(client, shop.headers, order_id)
    assert draft["version"] == response.json()["version"] == 2
    labor, part = draft["lines"]
    # 1,5 h × 45 € = 67,50 €; la pieza, 60 € − 10 % = 54 €: subtotal 121,50 €.
    # El descuento global de 5 € se reparte en proporción: 2,78 y 2,22 €.
    assert (labor["position"], part["position"]) == (1, 2)
    assert part["part_condition"] == "used"
    assert draft["totals"]["subtotal_cents"] == 12150
    assert draft["totals"]["global_discount_cents"] == 500
    assert [labor["taxable_cents"], part["taxable_cents"]] == [6472, 5178]
    # RNF-14: el IVA se redondea por línea y luego se suma (13,59 + 10,87 =
    # 24,46 €), no sobre la base sumada (116,50 × 21 % = 24,465 → 24,47 €).
    assert draft["totals"]["vat_breakdown"] == [
        {"vat_bp": 2100, "base_cents": 11650, "vat_cents": 2446}
    ]
    assert draft["totals"]["total_cents"] == 11650 + 2446
    # Un borrador no guarda importes: se calculan al leerlo.
    async with create_async_engine(os.environ["PLATFORM_DATABASE_URL"]).begin() as conn:
        stored = await conn.scalar(
            text("SELECT count(*) FROM quote_lines WHERE line_total_cents IS NOT NULL")
        )
    assert stored == 0


@pytest.mark.asyncio
async def test_a_part_without_condition_is_new(client: AsyncClient, shop: Shop) -> None:
    order_id = await new_order(client, shop)
    quote_id = await create(client, shop.headers, order_id)
    part = {key: value for key, value in PART.items() if key != "part_condition"}
    assert (await save(client, shop.headers, quote_id, 1, [part])).status_code == 200
    (draft,) = await quotes_of(client, shop.headers, order_id)
    assert draft["lines"][0]["part_condition"] == "new"


@pytest.mark.asyncio
async def test_an_order_has_one_draft_at_a_time(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await new_order(client, shop)
    await create(client, shop.headers, order_id)
    response = await client.post(f"{ORDERS}/{order_id}/quotes", headers=shop.headers)
    assert response.status_code == 409
    assert response.json()["code"] == "quote_draft_exists"


@pytest.mark.asyncio
async def test_rnf15_saving_from_an_old_version_is_a_409(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await new_order(client, shop)
    quote_id = await create(client, shop.headers, order_id)
    assert (await save(client, shop.headers, quote_id, 1, [LABOR])).status_code == 200
    stale = await save(client, shop.headers, quote_id, 1, [PART])
    assert stale.status_code == 409
    assert stale.json()["code"] == "modified_by_someone_else"
    (draft,) = await quotes_of(client, shop.headers, order_id)
    assert [line["description"] for line in draft["lines"]] == ["Mecánica"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lines", "discount", "code"),
    [
        # Un descuento global mayor que el presupuesto (RF-39).
        (
            [LABOR],
            {"kind": "amount", "value": 100_000},
            "global_discount_exceeds_subtotal",
        ),
        ([{**LABOR, "part_condition": "used"}], None, None),
        ([{**LABOR, "quantity": "1.0005"}], None, None),
        ([{**LABOR, "quantity": "0"}], None, None),
        ([{**LABOR, "vat_bp": 10_001}], None, None),
        ([LABOR], {"kind": "percent", "value": 10_001}, None),
        ([LABOR] * 201, None, None),
    ],
)
async def test_what_cannot_be_calculated_is_refused(
    client: AsyncClient,
    shop: Shop,
    lines: list[dict[str, Any]],
    discount: dict[str, Any] | None,
    code: str | None,
) -> None:
    order_id = await new_order(client, shop)
    quote_id = await create(client, shop.headers, order_id)
    response = await save(client, shop.headers, quote_id, 1, lines, discount)
    assert response.status_code == 422, response.text
    if code:
        assert response.json()["code"] == code


@pytest.mark.asyncio
async def test_a_draft_is_discarded_and_the_number_is_reused(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await new_order(client, shop)
    quote_id = await create(client, shop.headers, order_id)
    await save(client, shop.headers, quote_id, 1, [LABOR])
    stale = await client.post(
        f"{QUOTES}/{quote_id}/discard", json={"version": 1}, headers=shop.headers
    )
    assert stale.status_code == 409
    response = await client.post(
        f"{QUOTES}/{quote_id}/discard", json={"version": 2}, headers=shop.headers
    )
    assert response.status_code == 204
    assert await quotes_of(client, shop.headers, order_id) == []
    # Nunca se envió: el número vuelve a estar libre.
    await create(client, shop.headers, order_id)
    (draft,) = await quotes_of(client, shop.headers, order_id)
    assert draft["version_no"] == 1


# --- Corregir es crear la versión siguiente (RF-32) -----------------------------


@pytest.mark.asyncio
async def test_correcting_a_sent_quote_copies_it_into_the_next_version(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await new_order(client, shop)
    first = await create(client, shop.headers, order_id)
    await save(
        client, shop.headers, first, 1, [ONE_HUNDRED], {"kind": "percent", "value": 0}
    )
    await send_by_sql(first)
    # Enviada, ya no se guarda ni se descarta.
    refused = await save(client, shop.headers, first, 3, [LABOR])
    assert (refused.status_code, refused.json()["code"]) == (409, "quote_not_draft")

    second = await create(client, shop.headers, order_id)
    newer, older = await quotes_of(client, shop.headers, order_id)
    assert (newer["id"], newer["version_no"], newer["status"]) == (second, 2, "draft")
    assert (older["id"], older["status"]) == (first, "sent")
    # Copia lo que escribió quien la preparó, y el descuento.
    assert [line["description"] for line in newer["lines"]] == ["Diagnóstico"]
    assert newer["global_discount_kind"] == "percent"
    # La enviada enseña sus totales guardados.
    assert older["totals"]["total_cents"] == 12100
    assert older["lines"][0]["total_cents"] == 12100


@pytest.mark.asyncio
async def test_an_order_has_at_most_twenty_versions(
    client: AsyncClient, shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§10: más indica un uso anómalo. Con el límite a 1 para no enviar veinte."""
    from app.services import quotes as quote_service

    monkeypatch.setattr(quote_service, "MAX_VERSIONS_PER_ORDER", 1)
    order_id = await new_order(client, shop)
    first = await create(client, shop.headers, order_id)
    await save(client, shop.headers, first, 1, [ONE_HUNDRED])
    await send_by_sql(first)
    response = await client.post(f"{ORDERS}/{order_id}/quotes", headers=shop.headers)
    assert (response.status_code, response.json()["code"]) == (
        409,
        "quote_version_limit_reached",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["delivered", "cancelled"])
async def test_a_closed_order_gets_no_quotes(
    client: AsyncClient, shop: Shop, status: str
) -> None:
    """RF-26: una orden cerrada solo admite notas y su cobro."""
    order_id = await new_order(client, shop)
    quote_id = await create(client, shop.headers, order_id)
    await force_status(order_id, status)
    for response in (
        await client.post(f"{ORDERS}/{order_id}/quotes", headers=shop.headers),
        await save(client, shop.headers, quote_id, 1, [LABOR]),
    ):
        assert (response.status_code, response.json()["code"]) == (
            409,
            "work_order_closed",
        )


# --- Quién ve qué ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_mechanic_sees_the_quote_without_prices_if_the_workshop_says_so(
    client: AsyncClient, shop: Shop, outbox: InMemoryEmailSender
) -> None:
    mechanic = await invite_and_accept(
        client, shop.admin, outbox, await add_mechanic(client, shop.admin)
    )
    order_id = await new_order(client, shop)
    quote_id = await create(client, shop.headers, order_id)
    await save(client, shop.headers, quote_id, 1, [LABOR])
    (seen,) = await quotes_of(client, mechanic, order_id)
    assert seen["prices_hidden"] is False
    assert seen["lines"][0]["unit_price_cents"] == 4500

    settings = await client.get("/api/v1/workshop/settings", headers=shop.headers)
    await client.patch(
        "/api/v1/workshop/settings",
        json={
            "version": settings.json()["version"],
            "mechanics_see_sale_prices": False,
        },
        headers=shop.headers,
    )
    (seen,) = await quotes_of(client, mechanic, order_id)
    assert seen["prices_hidden"] is True
    assert seen["totals"] is None
    assert seen["lines"][0]["unit_price_cents"] is None
    assert seen["lines"][0]["total_cents"] is None
    # Lo que se hace sí lo ve: es lo que va a reparar.
    assert seen["lines"][0]["description"] == "Mecánica"
    # Y el administrador, siempre.
    (own,) = await quotes_of(client, shop.headers, order_id)
    assert own["lines"][0]["unit_price_cents"] == 4500


@pytest.mark.asyncio
async def test_the_quotes_of_another_workshop_do_not_exist(
    client: AsyncClient, shop: Shop
) -> None:
    """RNF-01: desde otro taller, 404 y no 403."""
    order_id = await new_order(client, shop)
    quote_id = await create(client, shop.headers, order_id)
    other = await open_workshop(client, "Talleres Gómez")
    for response in (
        await client.get(f"{ORDERS}/{order_id}/quotes", headers=other.headers),
        await client.post(f"{ORDERS}/{order_id}/quotes", headers=other.headers),
        await save(client, other.headers, quote_id, 1, [LABOR]),
        await client.post(
            f"{QUOTES}/{quote_id}/discard", json={"version": 1}, headers=other.headers
        ),
    ):
        assert response.status_code == 404, response.text
    (draft,) = await quotes_of(client, shop.headers, order_id)
    assert draft["version"] == 1


# --- Concurrencia -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_drafts_created_at_once_give_one_draft_and_a_409(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """Las dos pasan el "¿ya hay borrador?" sin verse (READ COMMITTED): el índice
    único para a la segunda, y llega como 409, no como un 500."""
    from app.services import quotes as quote_service

    order = await seed_order(engines, two_workshops)
    a = order.workshop_id
    employee = (
        await employee_with_access(engines, make_account, a, "admin")
    ).employee_id

    async with open_transaction(a) as first, open_transaction(a) as second:
        await quote_service.create_draft(first, a, employee, order.order_id)
        work = asyncio.create_task(
            quote_service.create_draft(second, a, employee, order.order_id)
        )
        await asyncio.sleep(GRACE)
        assert not work.done(), "la segunda debería esperar al índice único"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    assert outcome.code == "quote_draft_exists"
    async with engines.platform.connect() as conn:
        drafts = await conn.scalar(text("SELECT count(*) FROM quotes"))
    assert drafts == 1


# --- El listado de la barra lateral ---------------------------------------------


async def expire_by_sql(quote_id: str) -> None:
    """Deja pasar el plazo de una versión enviada: el dueño apaga el trigger
    dentro de su transacción, como hace la demo para mover fechas."""
    # El dueño también obedece RLS: el taller se lee antes con la plataforma.
    platform = create_async_engine(os.environ["PLATFORM_DATABASE_URL"])
    try:
        async with platform.connect() as conn:
            workshop = await conn.scalar(
                text("SELECT workshop_id FROM quotes WHERE id = :q"), {"q": quote_id}
            )
    finally:
        await platform.dispose()
    engine = create_async_engine(os.environ["MIGRATIONS_DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.workshop_ids', :w, true)"),
                {"w": "{" + str(workshop) + "}"},
            )
            await conn.execute(
                text("ALTER TABLE quotes DISABLE TRIGGER quotes_frozen_after_send")
            )
            await conn.execute(
                text(
                    "UPDATE quotes SET valid_until = clock_timestamp()"
                    " - interval '1 day' WHERE id = :q"
                ),
                {"q": quote_id},
            )
            await conn.execute(
                text("ALTER TABLE quotes ENABLE TRIGGER quotes_frozen_after_send")
            )
    finally:
        await engine.dispose()


async def listed(
    client: AsyncClient, headers: dict[str, str], view: str
) -> list[tuple[str, int, str, bool]]:
    response = await client.get(QUOTES, params={"view": view}, headers=headers)
    assert response.status_code == 200, response.text
    return [
        (q["order_code"], q["version_no"], q["status"], q["expired"])
        for q in response.json()
    ]


@pytest.mark.asyncio
async def test_the_list_shows_each_order_once_per_view(
    client: AsyncClient, shop: Shop
) -> None:
    """Pendientes (enviadas y en plazo), caducadas, borradores y, en "todos", la
    versión más reciente de cada orden."""
    corrected = await new_order(client, shop)  # v1 enviada y v2 en borrador
    drafted = await new_order(client, shop)  # solo un borrador
    expired = await new_order(client, shop)  # v1 enviada y fuera de plazo
    codes = {
        order_id: (
            await client.get(f"{ORDERS}/{order_id}", headers=shop.headers)
        ).json()["code"]
        for order_id in (corrected, drafted, expired)
    }
    for order_id in (corrected, expired):
        quote_id = await create(client, shop.headers, order_id)
        await save(client, shop.headers, quote_id, 1, [ONE_HUNDRED])
        await send_by_sql(quote_id)
        if order_id == expired:
            await expire_by_sql(quote_id)
    await create(client, shop.headers, corrected)
    await create(client, shop.headers, drafted)

    assert await listed(client, shop.headers, "pending") == [
        (codes[corrected], 1, "sent", False)
    ]
    assert await listed(client, shop.headers, "expired") == [
        (codes[expired], 1, "sent", True)
    ]
    assert sorted(await listed(client, shop.headers, "drafts")) == sorted(
        [(codes[corrected], 2, "draft", False), (codes[drafted], 1, "draft", False)]
    )
    assert sorted(await listed(client, shop.headers, "all")) == sorted(
        [
            (codes[corrected], 2, "draft", False),
            (codes[drafted], 1, "draft", False),
            (codes[expired], 1, "sent", True),
        ]
    )
    # La pestaña por defecto: las que esperan respuesta.
    default = await client.get(QUOTES, headers=shop.headers)
    assert [q["order_code"] for q in default.json()] == [codes[corrected]]
    (sent,) = default.json()
    assert (sent["total_cents"], sent["plate"]) == (12100, shop.car["plate"])


@pytest.mark.asyncio
async def test_the_list_hides_totals_from_mechanics_if_the_workshop_says_so(
    client: AsyncClient, shop: Shop, outbox: InMemoryEmailSender
) -> None:
    mechanic = await invite_and_accept(
        client, shop.admin, outbox, await add_mechanic(client, shop.admin)
    )
    order_id = await new_order(client, shop)
    quote_id = await create(client, shop.headers, order_id)
    await save(client, shop.headers, quote_id, 1, [ONE_HUNDRED])
    seen = await client.get(QUOTES, params={"view": "drafts"}, headers=mechanic)
    assert seen.json()[0]["total_cents"] == 12100
    settings = await client.get("/api/v1/workshop/settings", headers=shop.headers)
    await client.patch(
        "/api/v1/workshop/settings",
        json={
            "version": settings.json()["version"],
            "mechanics_see_sale_prices": False,
        },
        headers=shop.headers,
    )
    seen = await client.get(QUOTES, params={"view": "drafts"}, headers=mechanic)
    assert seen.json()[0]["total_cents"] is None


@pytest.mark.asyncio
async def test_the_list_only_has_quotes_of_the_active_workshop(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await new_order(client, shop)
    await create(client, shop.headers, order_id)
    other = await open_workshop(client, "Talleres Gómez")
    assert await listed(client, other.headers, "all") == []
    assert len(await listed(client, shop.headers, "all")) == 1
