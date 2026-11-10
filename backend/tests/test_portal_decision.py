"""El cliente aprueba o rechaza desde el portal (F4 paso 5: RF-34, RF-36, RNF-40).

Lo delicado: que solo decida lo suyo (RLS no separa a dos clientes de un taller),
que su decisión valga para la versión que vio y ninguna otra, que solo haya una, y
que lo personal que deja (IP, navegador y motivo) se pueda borrar al anonimizarlo
sin que lo decidido cambie.
"""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.domain.quotes import DecisionChannel, Outcome
from app.infra.email import InMemoryEmailSender
from tests.conftest import Engines, TwoWorkshops
from tests.test_anonymize import anonymize, dump_of_every_table
from tests.test_anonymize import read as read_client
from tests.test_clients import create as create_client
from tests.test_clients import open_workshop
from tests.test_concurrency import (
    GRACE,
    MakeAccount,
    dispose_global_engines,  # noqa: F401
    finish,
    open_transaction,
)
from tests.test_payment import deliver
from tests.test_portal_orders import (
    PORTAL,
    Portal,
    detail,
    enter,
    order_of_luis,
    portal,
    workshop_id_of,
)
from tests.test_quote_decision import decide, sent_order, sent_quote
from tests.test_quote_send import (
    cancel,
    diagnosing_order,
    draft_with_lines,
    order_of,
    send,
)
from tests.test_quotes import create, expire_by_sql, new_order, quotes_of
from tests.test_rls import set_workshops
from tests.test_vehicles import change_owner
from tests.test_vehicles import create as create_vehicle
from tests.test_work_orders import Shop, force_status, outbox

__all__ = ["outbox", "portal"]

BROWSER = "Mozilla/5.0 (Android 14; Pixel 8) NavegadorDeMaria/1.0"
REASON = "Me parece caro, lo pensaré con mi cuñado Ambrosio"


async def post_decision(
    client: AsyncClient,
    headers: dict[str, str],
    quote_id: str,
    outcome: str = "approved",
    reason: str | None = None,
    **extra: Any,
) -> Response:
    return await client.post(
        f"{PORTAL}/quotes/{quote_id}/decision",
        json={"outcome": outcome, "reason": reason, **extra},
        headers={**headers, "User-Agent": BROWSER},
    )


async def decision_row(engines: Engines, quote_id: Any) -> dict[str, Any] | None:
    async with engines.platform.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT outcome, channel, recorded_by_employee_id, host(ip) AS ip,"
                    " user_agent, note, decided_at FROM quote_decisions"
                    " WHERE quote_id = :q"
                ),
                {"q": quote_id},
            )
        ).one_or_none()
    return dict(row._mapping) if row else None


async def expect_conflict(response: Response, code: str) -> None:
    assert (response.status_code, response.json()["code"]) == (409, code)


async def luis_sent_quote(client: AsyncClient, shop: Shop) -> tuple[str, str]:
    """Una versión enviada de una orden de Luis, para intentar decidirla como María."""
    order_id = await order_of_luis(client, shop)
    await force_status(order_id, "diagnosing")
    quote_id = await draft_with_lines(client, shop, order_id)
    assert (await send(client, shop, order_id, quote_id)).status_code == 204
    return order_id, quote_id


# --- Aprobar y rechazar --------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_approval_keeps_the_proof_and_moves_the_order(
    client: AsyncClient, portal: Portal, engines: Engines
) -> None:
    """RF-36: la versión exacta, el resultado, el canal, la fecha, la IP y el navegador."""
    order_id, quote_id = await sent_order(client, portal.shop)

    response = await post_decision(client, portal.maria, quote_id)
    assert response.status_code == 204, response.text

    row = await decision_row(engines, quote_id)
    assert row is not None
    assert (row["outcome"], row["channel"]) == ("approved", "portal")
    assert row["recorded_by_employee_id"] is None
    assert row["ip"] == "127.0.0.1"
    assert row["user_agent"] == BROWSER
    assert row["note"] is None

    order = await order_of(client, portal.shop, order_id)
    assert order["status"] == "approved"
    last = order["history"][-1]
    assert (last["from_status"], last["to_status"], last["cause"]) == (
        "pending_approval",
        "approved",
        "quote_decided",
    )
    assert last["by_client"] is True
    assert last["employee_name"] is None

    audit = await client.get("/api/v1/workshop/audit", headers=portal.shop.headers)
    entry = audit.json()["entries"][0]
    assert (entry["action"], entry["actor"]) == ("quote_decided", None)
    assert entry["details"] == {
        "quote_version": 1,
        "quote_outcome": "approved",
        "decision_channel": "portal",
    }


@pytest.mark.asyncio
async def test_each_side_sees_the_decision_with_what_it_may_see(
    client: AsyncClient, portal: Portal
) -> None:
    order_id, quote_id = await sent_order(client, portal.shop)
    response = await post_decision(
        client, portal.maria, quote_id, "rejected", f"  {REASON}  "
    )
    assert response.status_code == 204, response.text

    seen = await detail(client, portal.maria, order_id)
    assert seen["quotes"][0]["status"] == "rejected"
    assert set(seen["quotes"][0]["decision"]) == {"outcome", "channel", "decided_at"}
    assert seen["quotes"][0]["decision"]["channel"] == "portal"

    (quote,) = await quotes_of(client, portal.shop.headers, order_id)
    assert quote["decision"]["channel"] == "portal"
    assert quote["decision"]["recorded_by_name"] is None
    assert quote["decision"]["note"] == REASON  # sin los espacios
    pdf = await client.get(
        f"/api/v1/workshop/quotes/{quote_id}/pdf", headers=portal.shop.headers
    )
    assert pdf.status_code == 200


@pytest.mark.asyncio
async def test_a_rejection_returns_the_order_and_keeps_the_reason_out_of_its_history(
    client: AsyncClient, portal: Portal
) -> None:
    """El historial no se puede tocar: lo escrito por el cliente iría allí para
    siempre, y al anonimizarlo no se podría borrar (RNF-40)."""
    order_id, quote_id = await sent_order(client, portal.shop)
    await post_decision(client, portal.maria, quote_id, "rejected", REASON)

    order = await order_of(client, portal.shop, order_id)
    assert order["status"] == "diagnosing"
    assert order["history"][-1]["by_client"] is True
    assert order["history"][-1]["note"] is None


@pytest.mark.asyncio
async def test_a_blank_reason_is_no_reason(
    client: AsyncClient, portal: Portal, engines: Engines
) -> None:
    _, quote_id = await sent_order(client, portal.shop)
    await post_decision(client, portal.maria, quote_id, "rejected", "   ")
    row = await decision_row(engines, quote_id)
    assert row is not None and row["note"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["approved", "rejected"])
async def test_an_additional_quote_decided_returns_to_the_repair(
    client: AsyncClient, portal: Portal, outcome: str
) -> None:
    order_id = await new_order(client, portal.shop)
    await force_status(order_id, "in_repair")
    quote_id = await draft_with_lines(client, portal.shop, order_id)
    await send(client, portal.shop, order_id, quote_id)

    response = await post_decision(client, portal.maria, quote_id, outcome)
    assert response.status_code == 204, response.text
    assert (await order_of(client, portal.shop, order_id))["status"] == "in_repair"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"outcome": "approved", "reason": "Un motivo para aprobar"},
        {"outcome": "rejected", "reason": "x" * 2001},
        {"outcome": "rejected", "reason": "con\x00nulo"},
        {"outcome": "maybe"},
        {},
    ],
)
async def test_a_malformed_decision_is_refused_and_records_nothing(
    client: AsyncClient, portal: Portal, engines: Engines, body: dict[str, Any]
) -> None:
    _, quote_id = await sent_order(client, portal.shop)
    response = await client.post(
        f"{PORTAL}/quotes/{quote_id}/decision", json=body, headers=portal.maria
    )
    assert response.status_code == 422, response.text
    assert await decision_row(engines, quote_id) is None


# --- T4: solo lo suyo -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_t4_a_client_cannot_decide_a_quote_of_another_client(
    client: AsyncClient, portal: Portal, engines: Engines
) -> None:
    """RLS no separa a María de Luis. Y no se distingue de una que no existe."""
    order_id, quote_id = await luis_sent_quote(client, portal.shop)

    theirs = await post_decision(client, portal.maria, quote_id)
    missing = await post_decision(client, portal.maria, str(uuid4()))
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json()
    assert await decision_row(engines, quote_id) is None
    assert (await order_of(client, portal.shop, order_id))["status"] == (
        "pending_approval"
    )

    # Luis sí: la prueba no pasa porque nadie pueda decidir.
    assert (await post_decision(client, portal.luis, quote_id)).status_code == 204


@pytest.mark.asyncio
async def test_t4_the_body_and_the_headers_do_not_choose_the_client(
    client: AsyncClient, portal: Portal, engines: Engines
) -> None:
    _, quote_id = await luis_sent_quote(client, portal.shop)
    response = await post_decision(
        client,
        {**portal.maria, "X-Client-Id": portal.shop.luis["id"]},
        quote_id,
        client_id=portal.shop.luis["id"],
    )
    assert response.status_code == 404
    assert await decision_row(engines, quote_id) is None


@pytest.mark.asyncio
async def test_t4_the_same_email_in_another_workshop_is_another_client(
    client: AsyncClient, outbox: InMemoryEmailSender, engines: Engines, portal: Portal
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

    assert (await post_decision(client, session_b, quote_id)).status_code == 404
    assert await decision_row(engines, quote_id) is None


@pytest.mark.asyncio
async def test_rf44_it_goes_by_the_order_not_by_the_current_owner(
    client: AsyncClient, portal: Portal
) -> None:
    """Si vendió el coche con la orden en marcha, la orden sigue siendo suya; quien
    lo compró no decide sobre ella (invariante 7)."""
    order_id, quote_id = await sent_order(client, portal.shop)
    await change_owner(
        client, portal.shop.headers, portal.shop.car, portal.shop.luis["id"]
    )

    assert (await post_decision(client, portal.luis, quote_id)).status_code == 404
    assert (await post_decision(client, portal.maria, quote_id)).status_code == 204
    assert (await order_of(client, portal.shop, order_id))["status"] == "approved"


@pytest.mark.asyncio
async def test_a_draft_does_not_exist_for_the_client(
    client: AsyncClient, portal: Portal
) -> None:
    order_id = await diagnosing_order(client, portal.shop)
    draft = await draft_with_lines(client, portal.shop, order_id)
    response = await post_decision(client, portal.maria, draft)
    assert (response.status_code, response.json()["code"]) == (404, "quote_not_found")


@pytest.mark.asyncio
async def test_only_a_client_session_can_decide(
    client: AsyncClient, portal: Portal, engines: Engines
) -> None:
    """Invariante 3: ni el personal ni nadie sin sesión entra por esta puerta."""
    _, quote_id = await sent_order(client, portal.shop)
    staff = await post_decision(client, portal.shop.headers, quote_id)
    nobody = await post_decision(client, {}, quote_id)
    assert staff.status_code == 403
    assert nobody.status_code == 401
    assert await decision_row(engines, quote_id) is None


# --- Solo la versión que vio, y solo una vez -------------------------------------------


@pytest.mark.asyncio
async def test_approving_a_replaced_version_never_counts_for_the_new_one(
    client: AsyncClient, portal: Portal, engines: Engines
) -> None:
    """El taller la corrige mientras el cliente la mira: aprobó un importe que ya
    no existe, y eso no puede convertirse en aprobar el nuevo."""
    order_id, first = await sent_order(client, portal.shop)
    second = await create(client, portal.shop.headers, order_id)
    assert (await send(client, portal.shop, order_id, second)).status_code == 204

    await expect_conflict(
        await post_decision(client, portal.maria, first), "quote_not_decidable"
    )
    assert await decision_row(engines, first) is None
    assert await decision_row(engines, second) is None
    assert (await order_of(client, portal.shop, order_id))["status"] == (
        "pending_approval"
    )
    assert (await post_decision(client, portal.maria, second)).status_code == 204


@pytest.mark.asyncio
async def test_a_cancelled_or_expired_version_cannot_be_decided(
    client: AsyncClient, portal: Portal, engines: Engines
) -> None:
    order_id, cancelled = await sent_order(client, portal.shop)
    await cancel(client, portal.shop, order_id, cancelled)
    await expect_conflict(
        await post_decision(client, portal.maria, cancelled), "quote_not_decidable"
    )

    _, expired = await sent_order(client, portal.shop)
    await expire_by_sql(expired)
    await expect_conflict(
        await post_decision(client, portal.maria, expired), "quote_expired"
    )
    assert await decision_row(engines, expired) is None


@pytest.mark.asyncio
async def test_a_decision_cannot_be_changed_by_deciding_again(
    client: AsyncClient, portal: Portal, engines: Engines
) -> None:
    order_id, quote_id = await sent_order(client, portal.shop)
    assert (await post_decision(client, portal.maria, quote_id)).status_code == 204
    await expect_conflict(
        await post_decision(client, portal.maria, quote_id, "rejected"),
        "quote_not_decidable",
    )
    row = await decision_row(engines, quote_id)
    assert row is not None and row["outcome"] == "approved"
    assert (await order_of(client, portal.shop, order_id))["status"] == "approved"


@pytest.mark.asyncio
async def test_the_workshop_cannot_decide_after_the_client(
    client: AsyncClient, portal: Portal
) -> None:
    order_id, quote_id = await sent_order(client, portal.shop)
    await post_decision(client, portal.maria, quote_id)
    response = await decide(client, portal.shop, order_id, quote_id, "rejected")
    await expect_conflict(response, "quote_not_decidable")


# --- Concurrencia: dos transacciones de verdad ------------------------------------------


async def client_of_order(engines: Engines, order_id: UUID) -> UUID:
    async with engines.platform.connect() as conn:
        found = await conn.scalar(
            text("SELECT client_id FROM work_orders WHERE id = :o"), {"o": order_id}
        )
    assert found is not None
    return UUID(str(found))


def portal_decision(
    session: AsyncSession,
    workshop_id: UUID,
    client_id: UUID,
    quote_id: UUID,
    outcome: Outcome = Outcome.APPROVED,
    ip: str | None = "203.0.113.7",
    user_agent: str | None = BROWSER,
) -> Any:
    from app.services import quotes as quote_service

    return quote_service.decide_from_portal(
        session,
        workshop_id,
        client_id,
        quote_id,
        outcome=outcome,
        reason=None,
        ip=ip,
        user_agent=user_agent,
    )


async def decisions_of(engines: Engines, quote_id: UUID) -> list[str]:
    async with engines.platform.connect() as conn:
        rows = await conn.scalars(
            text("SELECT outcome FROM quote_decisions WHERE quote_id = :q"),
            {"q": quote_id},
        )
        return list(rows.all())


@pytest.mark.asyncio
async def test_two_tabs_deciding_at_once_record_one(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """La segunda espera a la orden y encuentra la versión decidida: 409, no un
    choque con el UNIQUE de quote_id (500)."""
    order, _, quote_id, _ = await sent_quote(engines, two_workshops, make_account)
    a = order.workshop_id
    client_id = await client_of_order(engines, order.order_id)

    async with open_transaction(a) as first, open_transaction(a) as second:
        await portal_decision(first, a, client_id, quote_id, Outcome.APPROVED)
        work = asyncio.create_task(
            portal_decision(second, a, client_id, quote_id, Outcome.REJECTED)
        )
        await asyncio.sleep(GRACE)
        assert not work.done(), "la segunda decisión debería esperar"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    assert outcome.code == "quote_not_decidable"
    assert await decisions_of(engines, quote_id) == ["approved"]


@pytest.mark.asyncio
async def test_the_client_and_the_workshop_deciding_at_once_record_one(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    from app.services import quotes as quote_service

    order, staff, quote_id, version = await sent_quote(
        engines, two_workshops, make_account
    )
    a = order.workshop_id
    client_id = await client_of_order(engines, order.order_id)

    async with open_transaction(a) as first, open_transaction(a) as second:
        await quote_service.record_decision(
            first,
            a,
            staff.user_id,
            staff.employee_id,
            quote_id,
            expected_version=version,
            outcome=Outcome.REJECTED,
            channel=DecisionChannel.PHONE,
            note=None,
        )
        work = asyncio.create_task(portal_decision(second, a, client_id, quote_id))
        await asyncio.sleep(GRACE)
        assert not work.done(), "el cliente debería esperar a la orden"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    assert await decisions_of(engines, quote_id) == ["rejected"]


@pytest.mark.asyncio
async def test_approving_while_the_workshop_renews_never_approves_a_replaced_version(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    from app.services import quotes as quote_service

    order, staff, quote_id, version = await sent_quote(
        engines, two_workshops, make_account
    )
    a = order.workshop_id
    client_id = await client_of_order(engines, order.order_id)

    async with open_transaction(a) as first, open_transaction(a) as second:
        await quote_service.renew_quote(
            first,
            a,
            staff.user_id,
            staff.employee_id,
            quote_id,
            expected_version=version,
        )
        work = asyncio.create_task(portal_decision(second, a, client_id, quote_id))
        await asyncio.sleep(GRACE)
        assert not work.done(), "el cliente debería esperar a la renovación"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    assert outcome.code == "quote_not_decidable"
    assert await decisions_of(engines, quote_id) == []


@pytest.mark.asyncio
async def test_the_service_itself_refuses_another_clients_quote(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """El filtro no vive en el endpoint: quien llame al service lo tiene igual."""
    order, _, quote_id, _ = await sent_quote(engines, two_workshops, make_account)
    a = order.workshop_id
    async with open_transaction(a) as session:
        with pytest.raises(NotFoundError):
            await portal_decision(session, a, uuid4(), quote_id)


# --- La IP y el navegador ----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ip", "expected"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("2001:db8::1", "2001:db8::1"),
        ("unknown", None),  # request.client vacío
        ("no-es-una-ip", None),  # lo que traía X-Forwarded-For
    ],
)
async def test_an_odd_ip_is_never_a_reason_to_lose_the_decision(
    engines: Engines,
    two_workshops: TwoWorkshops,
    make_account: MakeAccount,
    ip: str,
    expected: str | None,
) -> None:
    """La columna es INET: sin comprobarla, un valor raro sería un 500 al aprobar."""
    order, _, quote_id, _ = await sent_quote(engines, two_workshops, make_account)
    a = order.workshop_id
    client_id = await client_of_order(engines, order.order_id)
    async with open_transaction(a) as session:
        await portal_decision(session, a, client_id, quote_id, ip=ip)
        await session.commit()
    row = await decision_row(engines, quote_id)
    assert row is not None and row["ip"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sent", "stored"), [("a" * 900, "a" * 500), ("", None), (None, None)]
)
async def test_the_browser_is_cut_to_its_column(
    engines: Engines,
    two_workshops: TwoWorkshops,
    make_account: MakeAccount,
    sent: str | None,
    stored: str | None,
) -> None:
    order, _, quote_id, _ = await sent_quote(engines, two_workshops, make_account)
    a = order.workshop_id
    client_id = await client_of_order(engines, order.order_id)
    async with open_transaction(a) as session:
        await portal_decision(session, a, client_id, quote_id, user_agent=sent)
        await session.commit()
    row = await decision_row(engines, quote_id)
    assert row is not None and row["user_agent"] == stored


# --- Anonimizar (RF-15, RNF-40) ----------------------------------------------------------


async def maria_rejected_and_delivered(
    client: AsyncClient, portal: Portal
) -> tuple[str, str]:
    order_id, quote_id = await sent_order(client, portal.shop)
    response = await post_decision(client, portal.maria, quote_id, "rejected", REASON)
    assert response.status_code == 204, response.text
    await deliver(order_id)
    return order_id, quote_id


@pytest.mark.asyncio
async def test_anonymizing_erases_what_is_personal_and_keeps_what_was_decided(
    client: AsyncClient, portal: Portal, engines: Engines
) -> None:
    _, quote_id = await maria_rejected_and_delivered(client, portal)
    before = await decision_row(engines, quote_id)
    assert before is not None and before["ip"] and before["user_agent"]

    maria = await read_client(client, portal.shop.headers, portal.shop.maria["id"])
    assert (await anonymize(client, portal.shop.headers, maria)).status_code == 204

    after = await decision_row(engines, quote_id)
    assert after is not None
    assert (after["ip"], after["user_agent"], after["note"]) == (None, None, None)
    for field in ("outcome", "channel", "decided_at"):
        assert after[field] == before[field], field

    dump = await dump_of_every_table()
    assert BROWSER.lower() not in dump
    assert REASON.lower() not in dump


@pytest.mark.asyncio
async def test_anonymizing_a_client_leaves_the_decisions_of_the_others_alone(
    client: AsyncClient, portal: Portal, engines: Engines
) -> None:
    await maria_rejected_and_delivered(client, portal)
    _, luis_quote = await luis_sent_quote(client, portal.shop)
    await post_decision(client, portal.luis, luis_quote, "rejected", "Otro motivo")

    maria = await read_client(client, portal.shop.headers, portal.shop.maria["id"])
    assert (await anonymize(client, portal.shop.headers, maria)).status_code == 204

    row = await decision_row(engines, luis_quote)
    assert row is not None
    assert (row["user_agent"], row["note"]) == (BROWSER, "Otro motivo")


@pytest.mark.asyncio
async def test_a_note_of_the_workshop_is_not_erased_by_anonymizing(
    client: AsyncClient, portal: Portal, engines: Engines
) -> None:
    """Solo se vacía lo que dejó el cliente en el portal."""
    order_id, quote_id = await sent_order(client, portal.shop)
    await decide(
        client, portal.shop, order_id, quote_id, note="Confirmado por teléfono"
    )
    await deliver(order_id)
    maria = await read_client(client, portal.shop.headers, portal.shop.maria["id"])
    assert (await anonymize(client, portal.shop.headers, maria)).status_code == 204
    row = await decision_row(engines, quote_id)
    assert row is not None and row["note"] == "Confirmado por teléfono"


ANONYMIZE_BY_SQL = (
    "UPDATE clients SET name = '', phone = '', email = NULL, tax_id = NULL,"
    " address = NULL, notes = NULL, archived_at = clock_timestamp(),"
    " anonymized_at = clock_timestamp() WHERE id = :c"
)
ERASE = "UPDATE quote_decisions SET ip = NULL, user_agent = NULL, note = NULL WHERE quote_id = :q"


async def refused(session: AsyncSession, sql: str, quote_id: Any, match: str) -> None:
    with pytest.raises(DBAPIError, match=match):
        async with session.begin_nested():
            await session.execute(text(sql), {"q": quote_id})


@pytest.mark.asyncio
async def test_the_trigger_only_lets_empty_the_three_fields_of_an_anonymized_client(
    client: AsyncClient, portal: Portal, engines: Engines
) -> None:
    """La excepción es exactamente esa, con el rol de la aplicación."""
    _, quote_id = await maria_rejected_and_delivered(client, portal)
    workshop_id = workshop_id_of(portal.shop)

    async with open_transaction(workshop_id) as session:
        # Sin anonimizar, nada.
        await refused(session, ERASE, quote_id, "cannot change")
        await session.execute(text(ANONYMIZE_BY_SQL), {"c": portal.shop.maria["id"]})
        # Ya anonimizado: las tres a la vez o ninguna.
        await refused(
            session,
            "UPDATE quote_decisions SET note = NULL WHERE quote_id = :q",
            quote_id,
            "cannot change",
        )
        await refused(
            session,
            "UPDATE quote_decisions SET note = 'otra' WHERE quote_id = :q",
            quote_id,
            "cannot change",
        )
        # Lo decidido no se concede a la aplicación ni como efecto secundario.
        await refused(
            session,
            "UPDATE quote_decisions SET outcome = 'approved', ip = NULL,"
            " user_agent = NULL, note = NULL WHERE quote_id = :q",
            quote_id,
            "permission denied",
        )
        await refused(
            session,
            "DELETE FROM quote_decisions WHERE quote_id = :q",
            quote_id,
            "permission denied",
        )
        result = await session.execute(text(ERASE), {"q": quote_id})
        assert result.rowcount == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_the_trigger_does_not_let_erase_a_decision_taken_by_phone(
    client: AsyncClient, portal: Portal
) -> None:
    order_id, quote_id = await sent_order(client, portal.shop)
    await decide(client, portal.shop, order_id, quote_id, note="Por teléfono")
    await deliver(order_id)

    async with open_transaction(workshop_id_of(portal.shop)) as session:
        await session.execute(text(ANONYMIZE_BY_SQL), {"c": portal.shop.maria["id"]})
        await refused(session, ERASE, quote_id, "cannot change")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE quote_decisions SET outcome = 'approved' WHERE quote_id = :q",
        (
            "UPDATE quote_decisions SET decided_at = decided_at - interval '1 day'"
            " WHERE quote_id = :q"
        ),
        "DELETE FROM quote_decisions WHERE quote_id = :q",
    ],
)
async def test_what_was_decided_does_not_change_even_for_the_owner_after_anonymizing(
    client: AsyncClient, portal: Portal, engines: Engines, statement: str
) -> None:
    """Con los tres campos ya vacíos, la excepción del trigger no abre nada más:
    el dueño de las tablas tampoco cambia el resultado ni la fecha (invariante 6)."""
    _, quote_id = await maria_rejected_and_delivered(client, portal)
    maria = await read_client(client, portal.shop.headers, portal.shop.maria["id"])
    assert (await anonymize(client, portal.shop.headers, maria)).status_code == 204

    with pytest.raises(DBAPIError, match="cannot change"):
        async with engines.owner.begin() as conn:
            await set_workshops(conn, workshop_id_of(portal.shop))
            await conn.execute(text(statement), {"q": quote_id})
