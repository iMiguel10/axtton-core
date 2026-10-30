"""Enviar y anular un presupuesto (F3 paso 5: arquitectura §7.1, especificación
§6, RF-32, RF-33, invariantes 5 y 6)."""

import asyncio
import os
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.errors import ConflictError
from app.domain.business_days import quote_valid_until
from app.domain.quotes import LineKind
from tests.conftest import Engines, TwoWorkshops
from tests.test_concurrency import (
    GRACE,
    MakeAccount,
    dispose_global_engines,  # noqa: F401
    employee_with_access,
    finish,
    open_transaction,
)
from tests.test_quotes import (
    ONE_HUNDRED,
    ORDERS,
    QUOTES,
    create,
    new_order,
    quotes_of,
    save,
)
from tests.test_work_orders import Shop, force_status, outbox, shop
from tests.test_work_orders_db import seed_order

__all__ = ["outbox", "shop"]


async def order_of(client: AsyncClient, shop: Shop, order_id: str) -> dict[str, Any]:
    response = await client.get(f"{ORDERS}/{order_id}", headers=shop.headers)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


async def diagnosing_order(client: AsyncClient, shop: Shop) -> str:
    """Una orden en diagnóstico, con su diagnóstico para el cliente escrito."""
    order_id = await new_order(client, shop)
    order = await order_of(client, shop, order_id)
    moved = await client.post(
        f"{ORDERS}/{order_id}/status",
        json={"version": order["version"], "to_status": "diagnosing"},
        headers=shop.headers,
    )
    assert moved.status_code == 204, moved.text
    saved = await client.post(
        f"{ORDERS}/{order_id}/diagnosis",
        json={"base_version_no": 0, "text": "Pastillas gastadas."},
        headers=shop.headers,
    )
    assert saved.status_code == 201, saved.text
    return order_id


async def draft_with_lines(client: AsyncClient, shop: Shop, order_id: str) -> str:
    quote_id = await create(client, shop.headers, order_id)
    current = next(
        q
        for q in await quotes_of(client, shop.headers, order_id)
        if q["id"] == quote_id
    )
    response = await save(
        client, shop.headers, quote_id, current["version"], [ONE_HUNDRED]
    )
    assert response.status_code == 200, response.text
    return quote_id


async def version_of(
    client: AsyncClient, shop: Shop, order_id: str, quote_id: str
) -> int:
    quote = next(
        q
        for q in await quotes_of(client, shop.headers, order_id)
        if q["id"] == quote_id
    )
    version: int = quote["version"]
    return version


async def send(client: AsyncClient, shop: Shop, order_id: str, quote_id: str) -> Any:
    version = await version_of(client, shop, order_id, quote_id)
    return await client.post(
        f"{QUOTES}/{quote_id}/send", json={"version": version}, headers=shop.headers
    )


async def cancel(
    client: AsyncClient, shop: Shop, order_id: str, quote_id: str, reason: str = "Error"
) -> Any:
    version = await version_of(client, shop, order_id, quote_id)
    return await client.post(
        f"{QUOTES}/{quote_id}/cancel",
        json={"version": version, "reason": reason},
        headers=shop.headers,
    )


async def stored_lines(quote_id: str) -> list[tuple[int | None, ...]]:
    engine = create_async_engine(os.environ["PLATFORM_DATABASE_URL"])
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT taxable_cents, vat_cents, line_total_cents FROM quote_lines"
                    " WHERE quote_id = :q ORDER BY position"
                ),
                {"q": quote_id},
            )
            return [tuple(row) for row in rows]
    finally:
        await engine.dispose()


# --- Enviar ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sending_freezes_the_totals_and_moves_the_order(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await diagnosing_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    response = await send(client, shop, order_id, quote_id)
    assert response.status_code == 204, response.text

    order = await order_of(client, shop, order_id)
    assert order["status"] == "pending_approval"
    last = order["history"][-1]
    assert (last["from_status"], last["to_status"], last["cause"]) == (
        "diagnosing",
        "pending_approval",
        "quote_sent",
    )
    (quote,) = await quotes_of(client, shop.headers, order_id)
    assert quote["status"] == "sent"
    assert quote["totals"]["total_cents"] == 12100
    # Los importes de cada línea quedan guardados (RNF-11, RNF-14).
    assert await stored_lines(quote_id) == [(10000, 2100, 12100)]
    # Doce días hábiles en la zona del taller (RF-33), hasta el final del último.
    sent_at = datetime.fromisoformat(quote["sent_at"])
    expected = quote_valid_until(sent_at, "Europe/Madrid", 12)
    assert datetime.fromisoformat(quote["valid_until"]) == expected
    audit = await client.get("/api/v1/workshop/audit", headers=shop.headers)
    entry = audit.json()["entries"][0]
    assert entry["action"] == "quote_sent"
    assert entry["details"] == {"quote_version": 1, "total_cents": 12100}


@pytest.mark.asyncio
async def test_the_sent_quote_carries_the_current_diagnosis_and_its_origin(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await diagnosing_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    await send(client, shop, order_id, quote_id)
    engine = create_async_engine(os.environ["PLATFORM_DATABASE_URL"])
    try:
        async with engine.connect() as conn:
            origin, diagnosis = (
                await conn.execute(
                    text(
                        "SELECT q.origin_status, d.text FROM quotes q"
                        " JOIN diagnosis_versions d ON d.id = q.diagnosis_version_id"
                        " WHERE q.id = :q"
                    ),
                    {"q": quote_id},
                )
            ).one()
    finally:
        await engine.dispose()
    assert (origin, diagnosis) == ("diagnosing", "Pastillas gastadas.")


@pytest.mark.asyncio
async def test_the_validity_follows_the_workshop_setting(
    client: AsyncClient, shop: Shop
) -> None:
    settings = await client.get("/api/v1/workshop/settings", headers=shop.headers)
    await client.patch(
        "/api/v1/workshop/settings",
        json={
            "version": settings.json()["version"],
            "quote_validity_business_days": 20,
        },
        headers=shop.headers,
    )
    order_id = await diagnosing_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    await send(client, shop, order_id, quote_id)
    (quote,) = await quotes_of(client, shop.headers, order_id)
    sent_at = datetime.fromisoformat(quote["sent_at"])
    assert datetime.fromisoformat(quote["valid_until"]) == quote_valid_until(
        sent_at, "Europe/Madrid", 20
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["received", "approved", "waiting_parts", "ready"])
async def test_a_quote_is_sent_only_after_diagnosing_or_during_the_repair(
    client: AsyncClient, shop: Shop, status: str
) -> None:
    order_id = await new_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    if status != "received":
        await force_status(order_id, status)
    response = await send(client, shop, order_id, quote_id)
    assert (response.status_code, response.json()["code"]) == (
        409,
        "quote_cannot_be_sent_now",
    )


@pytest.mark.asyncio
async def test_an_empty_draft_or_an_old_version_is_not_sent(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await diagnosing_order(client, shop)
    quote_id = await create(client, shop.headers, order_id)
    empty = await send(client, shop, order_id, quote_id)
    assert (empty.status_code, empty.json()["code"]) == (409, "quote_empty")
    await save(client, shop.headers, quote_id, 1, [ONE_HUNDRED])
    stale = await client.post(
        f"{QUOTES}/{quote_id}/send", json={"version": 1}, headers=shop.headers
    )
    assert (stale.status_code, stale.json()["code"]) == (
        409,
        "modified_by_someone_else",
    )
    sent = await send(client, shop, order_id, quote_id)
    assert sent.status_code == 204
    again = await send(client, shop, order_id, quote_id)
    assert (again.status_code, again.json()["code"]) == (409, "quote_not_draft")


@pytest.mark.asyncio
async def test_correcting_supersedes_the_previous_version(
    client: AsyncClient, shop: Shop
) -> None:
    """RF-32: la versión nueva sustituye a la enviada, que ya no se puede
    aprobar. La orden sigue esperando respuesta, sin un cambio de estado nuevo,
    y la nueva hereda adónde volver."""
    order_id = await diagnosing_order(client, shop)
    first = await draft_with_lines(client, shop, order_id)
    await send(client, shop, order_id, first)
    history = len((await order_of(client, shop, order_id))["history"])
    second = await create(client, shop.headers, order_id)
    assert (await send(client, shop, order_id, second)).status_code == 204

    newer, older = await quotes_of(client, shop.headers, order_id)
    assert (newer["id"], newer["status"]) == (second, "sent")
    assert (older["id"], older["status"]) == (first, "superseded")
    order = await order_of(client, shop, order_id)
    assert order["status"] == "pending_approval"
    assert len(order["history"]) == history
    # Anular la nueva devuelve la orden al diagnóstico, de donde salió la primera.
    assert (await cancel(client, shop, order_id, second)).status_code == 204
    assert (await order_of(client, shop, order_id))["status"] == "diagnosing"


@pytest.mark.asyncio
async def test_an_additional_quote_during_the_repair_returns_to_the_repair(
    client: AsyncClient, shop: Shop
) -> None:
    """§6: un adicional rechazado o anulado no detiene el trabajo ya aprobado."""
    order_id = await new_order(client, shop)
    await force_status(order_id, "in_repair")
    quote_id = await draft_with_lines(client, shop, order_id)
    await send(client, shop, order_id, quote_id)
    assert (await order_of(client, shop, order_id))["status"] == "pending_approval"
    await cancel(client, shop, order_id, quote_id, "El cliente prefiere esperar")
    order = await order_of(client, shop, order_id)
    assert order["status"] == "in_repair"
    assert order["history"][-1]["cause"] == "quote_cancelled"
    assert order["history"][-1]["note"] == "El cliente prefiere esperar"


# --- Anular ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelling_needs_a_reason_and_is_final(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await diagnosing_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    await send(client, shop, order_id, quote_id)
    version = await version_of(client, shop, order_id, quote_id)
    blank = await client.post(
        f"{QUOTES}/{quote_id}/cancel",
        json={"version": version, "reason": "   "},
        headers=shop.headers,
    )
    assert blank.status_code == 422
    assert (
        await cancel(client, shop, order_id, quote_id, "Precio mal")
    ).status_code == 204
    (quote,) = await quotes_of(client, shop.headers, order_id)
    assert (quote["status"], quote["cancel_reason"]) == ("cancelled", "Precio mal")
    again = await cancel(client, shop, order_id, quote_id)
    assert (again.status_code, again.json()["code"]) == (409, "quote_not_cancellable")
    audit = await client.get("/api/v1/workshop/audit", headers=shop.headers)
    assert audit.json()["entries"][0]["action"] == "quote_cancelled"


@pytest.mark.asyncio
async def test_a_draft_or_a_superseded_version_is_not_cancelled(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await diagnosing_order(client, shop)
    first = await draft_with_lines(client, shop, order_id)
    draft = await cancel(client, shop, order_id, first)
    assert (draft.status_code, draft.json()["code"]) == (409, "quote_not_cancellable")
    await send(client, shop, order_id, first)
    second = await create(client, shop.headers, order_id)
    await send(client, shop, order_id, second)
    superseded = await cancel(client, shop, order_id, first)
    assert (superseded.status_code, superseded.json()["code"]) == (
        409,
        "quote_not_cancellable",
    )


# --- Lo que el presupuesto cambia en la orden ---------------------------------------


@pytest.mark.asyncio
async def test_an_order_with_a_sent_quote_is_not_cancelled(
    client: AsyncClient, shop: Shop
) -> None:
    """§6: cancelar es solo para órdenes abiertas por error, sin presupuestos
    enviados (ni siquiera ya anulados). Un borrador nunca enviado no cuenta."""
    order_id = await diagnosing_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    await send(client, shop, order_id, quote_id)
    await cancel(client, shop, order_id, quote_id)
    order = await order_of(client, shop, order_id)
    refused = await client.post(
        f"{ORDERS}/{order_id}/status",
        json={"version": order["version"], "to_status": "cancelled", "note": "Error"},
        headers=shop.headers,
    )
    assert (refused.status_code, refused.json()["code"]) == (
        409,
        "work_order_has_quotes",
    )

    only_draft = await diagnosing_order(client, shop)
    await draft_with_lines(client, shop, only_draft)
    order = await order_of(client, shop, only_draft)
    allowed = await client.post(
        f"{ORDERS}/{only_draft}/status",
        json={"version": order["version"], "to_status": "cancelled", "note": "Error"},
        headers=shop.headers,
    )
    assert allowed.status_code == 204, allowed.text
    # Su borrador ya no sale en el listado: nunca se enviará.
    drafts = await client.get(QUOTES, params={"view": "drafts"}, headers=shop.headers)
    assert drafts.json() == []


@pytest.mark.asyncio
async def test_the_change_made_by_the_quote_cannot_be_undone(
    client: AsyncClient, shop: Shop
) -> None:
    """§6: solo se deshace un cambio manual; el del presupuesto, no."""
    order_id = await diagnosing_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    await send(client, shop, order_id, quote_id)
    order = await order_of(client, shop, order_id)
    response = await client.post(
        f"{ORDERS}/{order_id}/undo",
        json={"version": order["version"]},
        headers=shop.headers,
    )
    assert (response.status_code, response.json()["code"]) == (
        409,
        "cannot_undo_automatic",
    )


@pytest.mark.asyncio
async def test_a_waiting_order_has_no_manual_way_out(
    client: AsyncClient, shop: Shop
) -> None:
    """Salir de `pending_approval` lo provoca el presupuesto (§6): la ficha no
    ofrece ningún cambio manual mientras espera respuesta."""
    order_id = await diagnosing_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    await send(client, shop, order_id, quote_id)
    order = await order_of(client, shop, order_id)
    assert order["allowed_transitions"] == []


@pytest.mark.asyncio
async def test_a_quote_past_its_validity_says_so(
    client: AsyncClient, shop: Shop
) -> None:
    """Hasta el worker (F5) nadie marca `expired`: la ficha lo dice igual."""
    from tests.test_quotes import expire_by_sql

    order_id = await diagnosing_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    await send(client, shop, order_id, quote_id)
    (quote,) = await quotes_of(client, shop.headers, order_id)
    assert quote["expired"] is False
    await expire_by_sql(quote_id)
    (quote,) = await quotes_of(client, shop.headers, order_id)
    assert (quote["status"], quote["expired"]) == ("sent", True)
    # Caducada, se anula igual (§6).
    assert (await cancel(client, shop, order_id, quote_id)).status_code == 204


# --- Concurrencia -------------------------------------------------------------------


async def sendable_draft(engines: Engines, workshop_id: Any, order_id: Any) -> Any:
    """Una orden en diagnóstico con un borrador de una línea, escrito con la
    plataforma. Devuelve el id del borrador."""
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO work_order_status_changes"
                " (workshop_id, work_order_id, from_status, to_status, cause)"
                " VALUES (:w, :o, 'received', 'diagnosing', 'manual')"
            ),
            {"w": workshop_id, "o": order_id},
        )
        await conn.execute(
            text("UPDATE work_orders SET status = 'diagnosing' WHERE id = :o"),
            {"o": order_id},
        )
        employee = await conn.scalar(
            text("SELECT id FROM employees WHERE workshop_id = :w LIMIT 1"),
            {"w": workshop_id},
        )
        quote_id = await conn.scalar(
            text(
                "INSERT INTO quotes"
                " (workshop_id, work_order_id, version_no, created_by_employee_id)"
                " VALUES (:w, :o, 1, :e) RETURNING id"
            ),
            {"w": workshop_id, "o": order_id, "e": employee},
        )
        await conn.execute(
            text(
                "INSERT INTO quote_lines (workshop_id, quote_id, position, kind,"
                " description, quantity, unit_price_cents, vat_bp)"
                " VALUES (:w, :q, 1, 'labor', 'Mano de obra', 1, 10000, 2100)"
            ),
            {"w": workshop_id, "q": quote_id},
        )
    return quote_id


@pytest.mark.asyncio
async def test_a_draft_saved_while_it_is_being_sent_makes_the_send_wait_and_fail(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """El guardado tiene la orden con FOR SHARE; el envío la pide FOR UPDATE y
    espera. Al seguir, lee la versión de nuevo (populate_existing) y ve que
    cambió: 409, no un envío de lo que el otro ya no quería enviar."""
    from app.services import quotes as quote_service
    from app.services.quotes import LineInput

    order = await seed_order(engines, two_workshops)
    a = order.workshop_id
    staff = await employee_with_access(engines, make_account, a, "admin")
    quote_id = await sendable_draft(engines, a, order.order_id)
    line = LineInput(LineKind.OTHER, "Otra cosa", None, None, Decimal(2), 500, 0, 2100)

    async with open_transaction(a) as first, open_transaction(a) as second:
        await quote_service.save_draft(
            first, a, quote_id, expected_version=1, global_discount=None, lines=[line]
        )
        work = asyncio.create_task(
            quote_service.send_quote(
                second,
                a,
                staff.user_id,
                staff.employee_id,
                quote_id,
                expected_version=1,
            )
        )
        await asyncio.sleep(GRACE)
        assert not work.done(), "el envío debería esperar al guardado"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    assert outcome.code == "modified_by_someone_else"
    async with engines.platform.connect() as conn:
        status = await conn.scalar(
            text("SELECT status FROM quotes WHERE id = :q"), {"q": quote_id}
        )
    assert status == "draft"


@pytest.mark.asyncio
async def test_the_same_draft_sent_twice_at_once_is_sent_once(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """Dos envíos a la vez: el segundo espera a la orden y luego se encuentra
    la versión ya enviada (409), no un choque con el trigger (500)."""
    from app.services import quotes as quote_service

    order = await seed_order(engines, two_workshops)
    a = order.workshop_id
    staff = await employee_with_access(engines, make_account, a, "admin")
    quote_id = await sendable_draft(engines, a, order.order_id)

    async def send_it(session: Any) -> None:
        await quote_service.send_quote(
            session, a, staff.user_id, staff.employee_id, quote_id, expected_version=1
        )

    async with open_transaction(a) as first, open_transaction(a) as second:
        await send_it(first)
        work = asyncio.create_task(send_it(second))
        await asyncio.sleep(GRACE)
        assert not work.done(), "el segundo envío debería esperar a la orden"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    async with engines.platform.connect() as conn:
        changes = await conn.scalar(
            text(
                "SELECT count(*) FROM work_order_status_changes"
                " WHERE work_order_id = :o AND cause = 'quote_sent'"
            ),
            {"o": order.order_id},
        )
    assert changes == 1


@pytest.mark.asyncio
async def test_an_order_cancelled_while_its_quote_is_sent_is_refused(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """Enviar y cancelar la orden piden los dos la orden con FOR UPDATE: la
    cancelación espera, luego ve el presupuesto enviado y se rechaza (§6).
    Nunca queda una orden cancelada con un presupuesto esperando respuesta."""
    from app.services import quotes as quote_service
    from app.services import work_orders as order_service

    order = await seed_order(engines, two_workshops)
    a = order.workshop_id
    staff = await employee_with_access(engines, make_account, a, "admin")
    quote_id = await sendable_draft(engines, a, order.order_id)

    async with open_transaction(a) as first, open_transaction(a) as second:
        await quote_service.send_quote(
            first, a, staff.user_id, staff.employee_id, quote_id, expected_version=1
        )
        work = asyncio.create_task(
            order_service.change_status(
                second,
                order.order_id,
                staff.employee_id,
                "admin",
                expected_version=1,
                to_status="cancelled",
                note="Abierta por error",
            )
        )
        await asyncio.sleep(GRACE)
        assert not work.done(), "la cancelación debería esperar al envío"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    async with engines.platform.connect() as conn:
        status = await conn.scalar(
            text("SELECT status FROM work_orders WHERE id = :o"), {"o": order.order_id}
        )
    assert status == "pending_approval"


# --- Renovar (ampliar el plazo sin tocar lo enviado) ---------------------------------


async def renew(client: AsyncClient, shop: Shop, order_id: str, quote_id: str) -> Any:
    version = await version_of(client, shop, order_id, quote_id)
    return await client.post(
        f"{QUOTES}/{quote_id}/renew", json={"version": version}, headers=shop.headers
    )


@pytest.mark.asyncio
async def test_renewing_an_expired_quote_sends_a_copy_with_a_new_validity(
    client: AsyncClient, shop: Shop
) -> None:
    """Invariante 6: la caducada no cambia (sigue con su fecha y sus totales);
    la nueva copia sus líneas y precios, sale enviada y vale desde hoy."""
    from tests.test_quotes import expire_by_sql

    order_id = await diagnosing_order(client, shop)
    first = await draft_with_lines(client, shop, order_id)
    await send(client, shop, order_id, first)
    await expire_by_sql(first)
    (expired,) = await quotes_of(client, shop.headers, order_id)
    history = len((await order_of(client, shop, order_id))["history"])

    response = await renew(client, shop, order_id, first)
    assert response.status_code == 201, response.text
    renewed, old = await quotes_of(client, shop.headers, order_id)
    assert renewed["id"] == response.json()["id"]
    assert (renewed["version_no"], renewed["status"], renewed["expired"]) == (
        2,
        "sent",
        False,
    )
    assert (old["status"], old["valid_until"]) == ("superseded", expired["valid_until"])
    assert old["totals"] == expired["totals"]
    assert [line["description"] for line in renewed["lines"]] == ["Diagnóstico"]
    assert renewed["totals"]["total_cents"] == expired["totals"]["total_cents"]
    sent_at = datetime.fromisoformat(renewed["sent_at"])
    assert datetime.fromisoformat(renewed["valid_until"]) == quote_valid_until(
        sent_at, "Europe/Madrid", 12
    )
    # La orden sigue esperando respuesta, sin un cambio de estado nuevo, y la
    # renovada le deja su origen: anularla devuelve la orden al diagnóstico.
    order = await order_of(client, shop, order_id)
    assert (order["status"], len(order["history"])) == ("pending_approval", history)
    await cancel(client, shop, order_id, renewed["id"])
    assert (await order_of(client, shop, order_id))["status"] == "diagnosing"
    audit = await client.get("/api/v1/workshop/audit", headers=shop.headers)
    actions = [e["action"] for e in audit.json()["entries"]]
    assert "quote_renewed" in actions


@pytest.mark.asyncio
async def test_a_quote_still_in_time_can_also_be_renewed(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await diagnosing_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    await send(client, shop, order_id, quote_id)
    assert (await renew(client, shop, order_id, quote_id)).status_code == 201
    renewed, old = await quotes_of(client, shop.headers, order_id)
    assert (renewed["status"], old["status"]) == ("sent", "superseded")


@pytest.mark.asyncio
async def test_what_is_not_waiting_for_a_reply_is_not_renewed(
    client: AsyncClient, shop: Shop
) -> None:
    order_id = await diagnosing_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    draft = await renew(client, shop, order_id, quote_id)
    assert (draft.status_code, draft.json()["code"]) == (409, "quote_not_renewable")
    await send(client, shop, order_id, quote_id)
    await cancel(client, shop, order_id, quote_id)
    cancelled = await renew(client, shop, order_id, quote_id)
    assert (cancelled.status_code, cancelled.json()["code"]) == (
        409,
        "quote_not_renewable",
    )


@pytest.mark.asyncio
async def test_a_quote_with_a_correction_in_progress_is_not_renewed(
    client: AsyncClient, shop: Shop
) -> None:
    """Con un borrador abierto (una corrección a medias), renovar crearía otra
    versión nueva a la vez: se termina o se descarta antes."""
    order_id = await diagnosing_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    await send(client, shop, order_id, quote_id)
    await create(client, shop.headers, order_id)
    response = await renew(client, shop, order_id, quote_id)
    assert (response.status_code, response.json()["code"]) == (
        409,
        "quote_draft_exists",
    )


@pytest.mark.asyncio
async def test_a_renewal_and_a_correction_at_once_leave_one_new_version(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """Renovar bloquea la orden FOR UPDATE; crear el borrador de una corrección
    la pide FOR SHARE y espera. Al seguir, ya ve la versión renovada (la 2,
    enviada) y crea la 3: ni dos versiones con el mismo número ni un 500."""
    from app.services import quotes as quote_service

    order = await seed_order(engines, two_workshops)
    a = order.workshop_id
    staff = await employee_with_access(engines, make_account, a, "admin")
    quote_id = await sendable_draft(engines, a, order.order_id)
    async with open_transaction(a) as session:
        await quote_service.send_quote(
            session, a, staff.user_id, staff.employee_id, quote_id, expected_version=1
        )
        await session.commit()
    async with engines.platform.connect() as conn:
        version = await conn.scalar(
            text("SELECT version FROM quotes WHERE id = :q"), {"q": quote_id}
        )

    async with open_transaction(a) as first, open_transaction(a) as second:
        await quote_service.renew_quote(
            first,
            a,
            staff.user_id,
            staff.employee_id,
            quote_id,
            expected_version=version,
        )
        work = asyncio.create_task(
            quote_service.create_draft(second, a, staff.employee_id, order.order_id)
        )
        await asyncio.sleep(GRACE)
        assert not work.done(), "la corrección debería esperar a la renovación"
        await first.commit()
        outcome = await finish(second, work)

    assert not isinstance(outcome, Exception), outcome
    async with engines.platform.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT version_no, status FROM quotes WHERE work_order_id = :o"
                    " ORDER BY version_no"
                ),
                {"o": order.order_id},
            )
        ).all()
    assert [tuple(r) for r in rows] == [(1, "superseded"), (2, "sent"), (3, "draft")]
