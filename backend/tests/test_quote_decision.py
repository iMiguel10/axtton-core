"""La decisión registrada por el taller (F3 paso 6: RF-35, RF-36, RF-29;
especificación §6, arquitectura §7.1)."""

import asyncio
import os
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.errors import ConflictError
from app.domain.quotes import DecisionChannel, Outcome
from app.infra.email import InMemoryEmailSender
from tests.conftest import Engines, TwoWorkshops
from tests.test_concurrency import (
    GRACE,
    MakeAccount,
    dispose_global_engines,  # noqa: F401
    employee_with_access,
    finish,
    open_transaction,
)
from tests.test_employees import add_mechanic, invite_and_accept
from tests.test_quote_send import (
    cancel,
    diagnosing_order,
    draft_with_lines,
    order_of,
    send,
    sendable_draft,
    version_of,
)
from tests.test_quotes import (
    ONE_HUNDRED,
    ORDERS,
    QUOTES,
    create,
    expire_by_sql,
    new_order,
    quotes_of,
    save,
)
from tests.test_work_orders import Shop, force_status, outbox, shop
from tests.test_work_orders_db import seed_order

__all__ = ["outbox", "shop"]

UNPAID = f"{ORDERS}/unpaid"
EXTRA = {
    "kind": "other",
    "description": "Líquido de frenos",
    "quantity": "1",
    "unit_price_cents": 2000,
    "vat_bp": 2100,
}


async def decide(
    client: AsyncClient,
    shop: Shop,
    order_id: str,
    quote_id: str,
    outcome: str = "approved",
    channel: str = "phone",
    note: str | None = None,
) -> Any:
    version = await version_of(client, shop, order_id, quote_id)
    return await client.post(
        f"{QUOTES}/{quote_id}/decision",
        json={"version": version, "outcome": outcome, "channel": channel, "note": note},
        headers=shop.headers,
    )


async def sent_order(client: AsyncClient, shop: Shop) -> tuple[str, str]:
    order_id = await diagnosing_order(client, shop)
    quote_id = await draft_with_lines(client, shop, order_id)
    assert (await send(client, shop, order_id, quote_id)).status_code == 204
    return order_id, quote_id


# --- Aprobar y rechazar ------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_approval_by_phone_is_recorded_and_moves_the_order(
    client: AsyncClient, shop: Shop
) -> None:
    order_id, quote_id = await sent_order(client, shop)
    response = await decide(
        client, shop, order_id, quote_id, note="Lo confirma su hijo por teléfono"
    )
    assert response.status_code == 204, response.text

    (quote,) = await quotes_of(client, shop.headers, order_id)
    assert quote["status"] == "approved"
    decision = quote["decision"]
    assert (decision["outcome"], decision["channel"]) == ("approved", "phone")
    assert decision["recorded_by_name"]
    assert decision["note"] == "Lo confirma su hijo por teléfono"
    order = await order_of(client, shop, order_id)
    assert order["status"] == "approved"
    last = order["history"][-1]
    assert (last["from_status"], last["to_status"], last["cause"]) == (
        "pending_approval",
        "approved",
        "quote_decided",
    )
    audit = await client.get("/api/v1/workshop/audit", headers=shop.headers)
    entry = audit.json()["entries"][0]
    assert entry["action"] == "quote_decided"
    assert entry["details"] == {
        "quote_version": 1,
        "quote_outcome": "approved",
        "decision_channel": "phone",
    }
    # Aprobado, el mecánico ya puede pasarla a reparación (§6).
    assert "in_repair" in [t["to_status"] for t in order["allowed_transitions"]]


@pytest.mark.asyncio
async def test_a_rejection_in_person_returns_the_order_to_diagnosis(
    client: AsyncClient, shop: Shop
) -> None:
    order_id, quote_id = await sent_order(client, shop)
    response = await decide(client, shop, order_id, quote_id, "rejected", "in_person")
    assert response.status_code == 204
    (quote,) = await quotes_of(client, shop.headers, order_id)
    assert (quote["status"], quote["decision"]["channel"]) == ("rejected", "in_person")
    # Rechazado: vuelve al diagnóstico, y de ahí sale "lista · sin reparar" (§6).
    assert (await order_of(client, shop, order_id))["status"] == "diagnosing"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["approved", "rejected"])
async def test_an_additional_quote_decided_returns_to_the_repair(
    client: AsyncClient, shop: Shop, outcome: str
) -> None:
    """§6: un adicional aprobado sigue reparando; uno rechazado, también: no
    detiene el trabajo ya aprobado."""
    order_id = await new_order(client, shop)
    await force_status(order_id, "in_repair")
    quote_id = await draft_with_lines(client, shop, order_id)
    await send(client, shop, order_id, quote_id)
    assert (await decide(client, shop, order_id, quote_id, outcome)).status_code == 204
    assert (await order_of(client, shop, order_id))["status"] == "in_repair"


# --- Lo que no se puede decidir --------------------------------------------------------


@pytest.mark.asyncio
async def test_only_the_version_waiting_for_a_reply_is_decided(
    client: AsyncClient, shop: Shop
) -> None:
    """Arquitectura §7.1: una versión en borrador, sustituida, anulada o ya
    decidida da 409, y el portal mostrará la vigente."""
    order_id = await diagnosing_order(client, shop)
    first = await draft_with_lines(client, shop, order_id)
    draft = await decide(client, shop, order_id, first)
    assert (draft.status_code, draft.json()["code"]) == (409, "quote_not_decidable")
    await send(client, shop, order_id, first)
    second = await create(client, shop.headers, order_id)
    await send(client, shop, order_id, second)
    superseded = await decide(client, shop, order_id, first)
    assert (superseded.status_code, superseded.json()["code"]) == (
        409,
        "quote_not_decidable",
    )
    assert (await decide(client, shop, order_id, second)).status_code == 204
    twice = await decide(client, shop, order_id, second, "rejected")
    assert (twice.status_code, twice.json()["code"]) == (409, "quote_not_decidable")

    cancelled_order, cancelled = await sent_order(client, shop)
    await cancel(client, shop, cancelled_order, cancelled)
    response = await decide(client, shop, cancelled_order, cancelled)
    assert (response.status_code, response.json()["code"]) == (
        409,
        "quote_not_decidable",
    )


@pytest.mark.asyncio
async def test_an_expired_quote_is_not_decided(client: AsyncClient, shop: Shop) -> None:
    """RF-33: pasada la fecha, no se aprueba sin reenviarlo (renovarlo)."""
    order_id, quote_id = await sent_order(client, shop)
    await expire_by_sql(quote_id)
    response = await decide(client, shop, order_id, quote_id)
    assert (response.status_code, response.json()["code"]) == (409, "quote_expired")


@pytest.mark.asyncio
async def test_the_portal_channel_and_a_stale_version_are_refused(
    client: AsyncClient, shop: Shop
) -> None:
    order_id, quote_id = await sent_order(client, shop)
    portal = await decide(client, shop, order_id, quote_id, channel="portal")
    assert portal.status_code == 422
    stale = await client.post(
        f"{QUOTES}/{quote_id}/decision",
        json={"version": 0, "outcome": "approved", "channel": "phone"},
        headers=shop.headers,
    )
    assert (stale.status_code, stale.json()["code"]) == (
        409,
        "modified_by_someone_else",
    )


# --- El importe a cobrar (RF-29) ----------------------------------------------------------


async def deliver(order_id: str) -> None:
    """Entregada, como al entregarla de verdad: con su fecha de entrega, de la
    que salen los días pendientes (`force_status` solo cambia el estado)."""
    await force_status(order_id, "delivered")
    engine = create_async_engine(os.environ["PLATFORM_DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE work_orders SET delivered_at = clock_timestamp() WHERE id = :o"
                ),
                {"o": order_id},
            )
    finally:
        await engine.dispose()


async def unpaid(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.get(UNPAID, headers=headers)
    assert response.status_code == 200, response.text
    return {o["id"]: o["amount_cents"] for o in response.json()}


@pytest.mark.asyncio
async def test_the_unpaid_list_shows_the_last_approved_total(
    client: AsyncClient, shop: Shop
) -> None:
    """El importe es el de la última versión aprobada, no la suma: el adicional
    copia lo aprobado antes y le añade lo nuevo. Rechazado el adicional, vale la
    anterior. Sin presupuesto aprobado, no hay importe."""
    approved_only, quote_id = await sent_order(client, shop)
    await decide(client, shop, approved_only, quote_id)

    with_extra, first = await sent_order(client, shop)
    await decide(client, shop, with_extra, first)
    await force_status(with_extra, "in_repair")
    extra = await create(client, shop.headers, with_extra)
    version = await version_of(client, shop, with_extra, extra)
    await save(client, shop.headers, extra, version, [ONE_HUNDRED, EXTRA])
    await send(client, shop, with_extra, extra)
    await decide(client, shop, with_extra, extra)

    rejected_extra, base = await sent_order(client, shop)
    await decide(client, shop, rejected_extra, base)
    await force_status(rejected_extra, "in_repair")
    more = await create(client, shop.headers, rejected_extra)
    version = await version_of(client, shop, rejected_extra, more)
    await save(client, shop.headers, more, version, [ONE_HUNDRED, EXTRA])
    await send(client, shop, rejected_extra, more)
    await decide(client, shop, rejected_extra, more, "rejected")

    no_quote = await new_order(client, shop)
    for order_id in (approved_only, with_extra, rejected_extra, no_quote):
        await deliver(order_id)

    amounts = await unpaid(client, shop.headers)
    assert amounts[approved_only] == 12100
    assert amounts[with_extra] == 12100 + 2420
    assert amounts[rejected_extra] == 12100
    assert amounts[no_quote] is None


@pytest.mark.asyncio
async def test_the_unpaid_amount_is_hidden_from_mechanics_if_the_workshop_says_so(
    client: AsyncClient, shop: Shop, outbox: InMemoryEmailSender
) -> None:
    mechanic = await invite_and_accept(
        client, shop.admin, outbox, await add_mechanic(client, shop.admin)
    )
    order_id, quote_id = await sent_order(client, shop)
    await decide(client, shop, order_id, quote_id)
    await deliver(order_id)
    assert (await unpaid(client, mechanic))[order_id] == 12100
    settings = await client.get("/api/v1/workshop/settings", headers=shop.headers)
    await client.patch(
        "/api/v1/workshop/settings",
        json={
            "version": settings.json()["version"],
            "mechanics_see_sale_prices": False,
        },
        headers=shop.headers,
    )
    assert (await unpaid(client, mechanic))[order_id] is None
    assert (await unpaid(client, shop.headers))[order_id] == 12100


# --- Concurrencia -------------------------------------------------------------------


async def sent_quote(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> tuple[Any, Any, Any, int]:
    """Una orden con su versión enviada por el service. Devuelve la orden, quién
    actúa, el id de la versión y su `version`."""
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
    return order, staff, quote_id, version


@pytest.mark.asyncio
async def test_two_decisions_at_once_record_one(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """Dos personas registran a la vez una aprobación y un rechazo: la segunda
    espera a la orden y se encuentra la versión ya decidida (409), no un choque
    con el UNIQUE de quote_id (500). Queda una sola decisión."""
    from app.services import quotes as quote_service

    order, staff, quote_id, version = await sent_quote(
        engines, two_workshops, make_account
    )
    a = order.workshop_id

    def decide_as(session: Any, outcome: Outcome) -> Any:
        return quote_service.record_decision(
            session,
            a,
            staff.user_id,
            staff.employee_id,
            quote_id,
            expected_version=version,
            outcome=outcome,
            channel=DecisionChannel.PHONE,
            note=None,
        )

    async with open_transaction(a) as first, open_transaction(a) as second:
        await decide_as(first, Outcome.APPROVED)
        work = asyncio.create_task(decide_as(second, Outcome.REJECTED))
        await asyncio.sleep(GRACE)
        assert not work.done(), "la segunda decisión debería esperar"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    async with engines.platform.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT outcome FROM quote_decisions WHERE quote_id = :q"),
                {"q": quote_id},
            )
        ).all()
        status = await conn.scalar(
            text("SELECT status FROM work_orders WHERE id = :o"), {"o": order.order_id}
        )
    assert [r[0] for r in rows] == ["approved"]
    assert status == "approved"


@pytest.mark.asyncio
async def test_a_decision_and_a_renewal_at_once_never_both_apply(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """Aprobar la versión que otro está renovando: la renovación espera, luego
    ve la versión aprobada y se rechaza. Nunca queda una aprobada sustituida."""
    from app.services import quotes as quote_service

    order, staff, quote_id, version = await sent_quote(
        engines, two_workshops, make_account
    )
    a = order.workshop_id

    async with open_transaction(a) as first, open_transaction(a) as second:
        await quote_service.record_decision(
            first,
            a,
            staff.user_id,
            staff.employee_id,
            quote_id,
            expected_version=version,
            outcome=Outcome.APPROVED,
            channel=DecisionChannel.IN_PERSON,
            note=None,
        )
        work = asyncio.create_task(
            quote_service.renew_quote(
                second,
                a,
                staff.user_id,
                staff.employee_id,
                quote_id,
                expected_version=version,
            )
        )
        await asyncio.sleep(GRACE)
        assert not work.done(), "la renovación debería esperar a la decisión"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    async with engines.platform.connect() as conn:
        statuses = (
            await conn.execute(
                text(
                    "SELECT status FROM quotes WHERE work_order_id = :o ORDER BY version_no"
                ),
                {"o": order.order_id},
            )
        ).all()
    assert [s[0] for s in statuses] == ["approved"]
