"""Presupuestos en la base de datos, sin pasar por el código (F3 paso 3).

Invariante 6 y RNF-11: una versión enviada y su decisión no cambian jamás, ni
desde la base de datos. Aquí se intenta romper cada garantía de la migración
0013quotes con SQL, con los tres roles: la aplicación, la plataforma y el dueño
de las tablas (R6).
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from tests.conftest import Engines, TwoWorkshops
from tests.test_rls import set_workshops
from tests.test_work_orders_db import Order, seed_order

GRACE = 0.5


@dataclass(frozen=True)
class Quotes:
    order: Order
    admin: UUID
    draft: UUID
    sent: UUID


async def add_quote(
    conn: AsyncConnection, order: Order, employee: UUID, version_no: int
) -> UUID:
    quote_id: UUID = await conn.scalar(
        text(
            "INSERT INTO quotes"
            " (workshop_id, work_order_id, version_no, created_by_employee_id)"
            " VALUES (:w, :o, :n, :e) RETURNING id"
        ),
        {"w": order.workshop_id, "o": order.order_id, "n": version_no, "e": employee},
    )
    return quote_id


async def add_line(
    conn: AsyncConnection, order: Order, quote_id: UUID, position: int = 1
) -> UUID:
    line_id: UUID = await conn.scalar(
        text(
            "INSERT INTO quote_lines (workshop_id, quote_id, position, kind,"
            " description, quantity, unit_price_cents, vat_bp)"
            " VALUES (:w, :q, :p, 'labor', 'Mano de obra', 1, 10000, 2100)"
            " RETURNING id"
        ),
        {"w": order.workshop_id, "q": quote_id, "p": position},
    )
    return line_id


async def calculate_lines(conn: AsyncConnection, quote_id: UUID) -> None:
    """Lo que hace el service al enviar, antes de marcar la versión: los
    importes de cada línea (aquí, 100 € + 21 %)."""
    await conn.execute(
        text(
            "UPDATE quote_lines SET gross_cents = 10000, discount_cents = 0,"
            " global_discount_share_cents = 0, taxable_cents = 10000,"
            " vat_cents = 2100, line_total_cents = 12100 WHERE quote_id = :q"
        ),
        {"q": quote_id},
    )


SEND = (
    "UPDATE quotes SET status = 'sent', sent_at = clock_timestamp(),"
    " sent_by_employee_id = :e, valid_until = clock_timestamp() + interval '20 days',"
    " origin_status = 'diagnosing', subtotal_cents = :t / 121 * 100,"
    " global_discount_cents = 0, vat_breakdown = '[]', total_cents = :t"
    " WHERE id = :q"
)


async def send(
    conn: AsyncConnection, quote_id: UUID, employee: UUID, total: int = 12100
) -> None:
    await calculate_lines(conn, quote_id)
    await conn.execute(text(SEND), {"q": quote_id, "e": employee, "t": total})


@pytest_asyncio.fixture
async def quotes(engines: Engines, two_workshops: TwoWorkshops) -> Quotes:
    """Una orden del taller A con la versión 1 enviada y la 2 en borrador."""
    order = await seed_order(engines, two_workshops)
    admin = two_workshops.admin_a
    async with engines.platform.begin() as conn:
        sent = await add_quote(conn, order, admin, 1)
        await add_line(conn, order, sent)
        await send(conn, sent, admin)
        draft = await add_quote(conn, order, admin, 2)
        await add_line(conn, order, draft)
    return Quotes(order, admin, draft, sent)


async def as_role(engine: AsyncEngine, quotes: Quotes, statement: str) -> None:
    """Ejecuta una sentencia con el taller de la orden fijado (el dueño también
    obedece RLS: sin taller, no vería la fila y no probaría nada)."""
    async with engine.begin() as conn:
        await set_workshops(conn, quotes.order.workshop_id)
        await conn.execute(
            text(statement),
            {
                "sent": quotes.sent,
                "draft": quotes.draft,
                "w": quotes.order.workshop_id,
                "e": quotes.admin,
            },
        )


def engines_by_role(engines: Engines) -> dict[str, AsyncEngine]:
    return {"app": engines.app, "platform": engines.platform, "owner": engines.owner}


# --- El borrador se edita libremente (RF-31) -----------------------------------


@pytest.mark.asyncio
async def test_the_app_edits_the_lines_of_a_draft(
    engines: Engines, quotes: Quotes
) -> None:
    async with engines.app.begin() as conn:
        await set_workshops(conn, quotes.order.workshop_id)
        await add_line(conn, quotes.order, quotes.draft, position=2)
        await conn.execute(
            text("UPDATE quote_lines SET quantity = 2 WHERE quote_id = :q"),
            {"q": quotes.draft},
        )
        await conn.execute(
            text("DELETE FROM quote_lines WHERE quote_id = :q AND position = 2"),
            {"q": quotes.draft},
        )
        # Y descartarlo es borrarlo, con sus líneas antes.
        await conn.execute(
            text("DELETE FROM quote_lines WHERE quote_id = :q"), {"q": quotes.draft}
        )
        await conn.execute(
            text("DELETE FROM quotes WHERE id = :q"), {"q": quotes.draft}
        )


# --- R6: una versión enviada no se toca ni por SQL ------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform", "owner"])
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE quote_lines SET unit_price_cents = 1 WHERE quote_id = :sent",
        "UPDATE quote_lines SET line_total_cents = line_total_cents WHERE quote_id = :sent",
        "DELETE FROM quote_lines WHERE quote_id = :sent",
        (
            "INSERT INTO quote_lines (workshop_id, quote_id, position, kind,"
            " description, quantity, unit_price_cents, vat_bp)"
            " VALUES (:w, :sent, 9, 'other', 'Extra', 1, 1, 0)"
        ),
    ],
)
async def test_r6_the_lines_of_a_sent_quote_are_frozen_for_every_role(
    engines: Engines, quotes: Quotes, role: str, statement: str
) -> None:
    with pytest.raises(DBAPIError, match="is not a draft: its lines are frozen"):
        await as_role(engines_by_role(engines)[role], quotes, statement)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["platform", "owner"])
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE quotes SET total_cents = 1 WHERE id = :sent",
        "UPDATE quotes SET valid_until = valid_until + interval '1 year' WHERE id = :sent",
        "UPDATE quotes SET vat_breakdown = '[{}]' WHERE id = :sent",
        (
            "UPDATE quotes SET global_discount_kind = 'amount',"
            " global_discount_value = 0 WHERE id = :sent"
        ),
    ],
)
async def test_r6_a_sent_quote_only_changes_its_status_for_every_role(
    engines: Engines, quotes: Quotes, role: str, statement: str
) -> None:
    with pytest.raises(DBAPIError, match="was sent: it cannot change"):
        await as_role(engines_by_role(engines)[role], quotes, statement)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform", "owner"])
async def test_a_sent_quote_cannot_be_deleted(
    engines: Engines, quotes: Quotes, role: str
) -> None:
    with pytest.raises(DBAPIError, match="only a draft quote can be discarded"):
        await as_role(
            engines_by_role(engines)[role],
            quotes,
            "DELETE FROM quotes WHERE id = :sent",
        )


@pytest.mark.asyncio
async def test_the_app_cannot_move_a_quote_or_renumber_it(
    engines: Engines, quotes: Quotes
) -> None:
    """Por permisos de columna, y para los demás roles, por el trigger."""
    for statement in (
        "UPDATE quotes SET version_no = 7 WHERE id = :draft",
        "UPDATE quote_lines SET quote_id = :sent WHERE quote_id = :draft",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            await as_role(engines.app, quotes, statement)
    with pytest.raises(DBAPIError, match="cannot change its order or version number"):
        await as_role(
            engines.platform,
            quotes,
            "UPDATE quotes SET version_no = 7 WHERE id = :draft",
        )
    with pytest.raises(DBAPIError, match="cannot move to another quote"):
        await as_role(
            engines.platform,
            quotes,
            "UPDATE quote_lines SET quote_id = :sent WHERE quote_id = :draft",
        )


# --- El paso de estado ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_sent_quote_is_cancelled_with_a_reason_and_then_is_final(
    engines: Engines, quotes: Quotes
) -> None:
    await as_role(
        engines.app,
        quotes,
        "UPDATE quotes SET status = 'cancelled', cancel_reason = 'Error' WHERE id = :sent",
    )
    for statement in (
        "UPDATE quotes SET status = 'sent', cancel_reason = NULL WHERE id = :sent",
        "UPDATE quotes SET cancel_reason = 'Otro motivo' WHERE id = :sent",
    ):
        with pytest.raises(DBAPIError, match="cannot go from cancelled|cannot change"):
            await as_role(engines.platform, quotes, statement)


@pytest.mark.asyncio
async def test_cancelling_needs_a_reason(engines: Engines, quotes: Quotes) -> None:
    with pytest.raises(DBAPIError, match="ck_quotes_cancel_reason"):
        await as_role(
            engines.app,
            quotes,
            "UPDATE quotes SET status = 'cancelled' WHERE id = :sent",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("UPDATE quotes SET status = 'sent' WHERE id = :sent", None),
        ("UPDATE quotes SET status = 'draft' WHERE id = :sent", "cannot go from sent"),
        # Aprobar sin la decisión registrada.
        (
            "UPDATE quotes SET status = 'approved' WHERE id = :sent",
            "needs its decision",
        ),
        ("UPDATE quotes SET status = 'expired' WHERE id = :sent", None),
    ],
)
async def test_the_status_of_a_sent_quote_follows_the_lifecycle(
    engines: Engines, quotes: Quotes, statement: str, message: str | None
) -> None:
    if message is None:
        await as_role(engines.platform, quotes, statement)
        return
    with pytest.raises(DBAPIError, match=message):
        await as_role(engines.platform, quotes, statement)


@pytest.mark.asyncio
async def test_an_expired_quote_can_only_be_cancelled_or_superseded(
    engines: Engines, quotes: Quotes
) -> None:
    await as_role(
        engines.app, quotes, "UPDATE quotes SET status = 'expired' WHERE id = :sent"
    )
    with pytest.raises(DBAPIError, match="only a sent quote can be decided"):
        await as_role(
            engines.app,
            quotes,
            "INSERT INTO quote_decisions"
            " (workshop_id, quote_id, outcome, channel, recorded_by_employee_id)"
            " VALUES (:w, :sent, 'approved', 'phone', :e)",
        )
    await as_role(
        engines.app, quotes, "UPDATE quotes SET status = 'superseded' WHERE id = :sent"
    )


@pytest.mark.asyncio
async def test_a_draft_can_only_be_sent(engines: Engines, quotes: Quotes) -> None:
    with pytest.raises(DBAPIError, match="a draft quote can only be sent"):
        await as_role(
            engines.platform,
            quotes,
            "UPDATE quotes SET status = 'cancelled', cancel_reason = 'x' WHERE id = :draft",
        )


# --- Enviar: los totales se escriben antes y cuadran (RNF-14) -----------------------


@pytest.mark.asyncio
async def test_a_draft_is_sent_only_with_its_lines_calculated(
    engines: Engines, quotes: Quotes
) -> None:
    """La trampa de F0: los importes de las líneas van antes de marcar la
    versión. Al revés, el trigger de las líneas ya la vería enviada."""
    params = {"q": quotes.draft, "e": quotes.admin, "t": 12100}
    # Sin calcular las líneas.
    async with engines.platform.begin() as conn:
        # La versión 1 ya está enviada: se sustituye antes (un solo `sent`).
        await conn.execute(
            text("UPDATE quotes SET status = 'superseded' WHERE id = :q"),
            {"q": quotes.sent},
        )
        with pytest.raises(DBAPIError, match="must be calculated and add up"):
            await conn.execute(text(SEND), params)
    # Calculadas, pero el total guardado no es su suma.
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE quotes SET status = 'superseded' WHERE id = :q"),
            {"q": quotes.sent},
        )
        await calculate_lines(conn, quotes.draft)
        with pytest.raises(DBAPIError, match="must be calculated and add up"):
            await conn.execute(text(SEND), {**params, "t": 12099})
    # Bien hecho, pasa.
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE quotes SET status = 'superseded' WHERE id = :q"),
            {"q": quotes.sent},
        )
        await send(conn, quotes.draft, quotes.admin)


@pytest.mark.asyncio
async def test_a_draft_without_lines_cannot_be_sent(
    engines: Engines, quotes: Quotes
) -> None:
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("DELETE FROM quote_lines WHERE quote_id = :q"), {"q": quotes.draft}
        )
        await conn.execute(
            text("UPDATE quotes SET status = 'superseded' WHERE id = :q"),
            {"q": quotes.sent},
        )
        with pytest.raises(DBAPIError, match="must be calculated and add up"):
            await conn.execute(
                text(SEND), {"q": quotes.draft, "e": quotes.admin, "t": 0}
            )


@pytest.mark.asyncio
async def test_a_sent_quote_has_everything_and_a_draft_nothing(
    engines: Engines, quotes: Quotes
) -> None:
    with pytest.raises(DBAPIError, match="ck_quotes_sent_fields"):
        await as_role(
            engines.app, quotes, "UPDATE quotes SET total_cents = 1 WHERE id = :draft"
        )


@pytest.mark.asyncio
async def test_two_sent_versions_of_one_order_cannot_coexist(
    engines: Engines, quotes: Quotes
) -> None:
    """Aunque el service olvidara sustituir la anterior (arquitectura §7.1)."""
    async with engines.platform.begin() as conn:
        with pytest.raises(DBAPIError, match="uq_quotes_work_order_id_sent"):
            await send(conn, quotes.draft, quotes.admin)


@pytest.mark.asyncio
async def test_an_order_has_one_draft_at_a_time(
    engines: Engines, quotes: Quotes
) -> None:
    async with engines.app.begin() as conn:
        await set_workshops(conn, quotes.order.workshop_id)
        with pytest.raises(DBAPIError, match="uq_quotes_work_order_id_draft"):
            await add_quote(conn, quotes.order, quotes.admin, 3)


@pytest.mark.asyncio
async def test_a_part_line_says_its_condition_and_only_parts_do(
    engines: Engines, quotes: Quotes
) -> None:
    """RF-38: una pieza usada o reacondicionada se marca, y toda pieza lo dice."""
    insert = (
        "INSERT INTO quote_lines (workshop_id, quote_id, position, kind, description,"
        " part_condition, quantity, unit_price_cents, vat_bp)"
        " VALUES (:w, :draft, 5, '{kind}', 'Pieza', {condition}, 1, 100, 2100)"
    )
    for kind, condition in (("part", "NULL"), ("labor", "'used'")):
        with pytest.raises(DBAPIError, match="ck_quote_lines_part_condition"):
            await as_role(
                engines.app, quotes, insert.format(kind=kind, condition=condition)
            )
    await as_role(engines.app, quotes, insert.format(kind="part", condition="'used'"))


@pytest.mark.asyncio
async def test_a_quote_cannot_carry_the_diagnosis_of_another_order(
    engines: Engines, quotes: Quotes, two_workshops: TwoWorkshops
) -> None:
    async with engines.platform.begin() as conn:
        # Otra orden del mismo coche y el mismo cliente, con su diagnóstico.
        other = await conn.scalar(
            text(
                "INSERT INTO work_orders (workshop_id, year, number, type,"
                " vehicle_id, client_id, status)"
                " SELECT workshop_id, year, 2, type, vehicle_id, client_id, status"
                " FROM work_orders WHERE id = :o RETURNING id"
            ),
            {"o": quotes.order.order_id},
        )
        await conn.execute(
            text(
                "INSERT INTO work_order_status_changes"
                " (workshop_id, work_order_id, to_status, cause)"
                " VALUES (:w, :o, 'received', 'opened')"
            ),
            {"w": quotes.order.workshop_id, "o": other},
        )
        foreign = await conn.scalar(
            text(
                "INSERT INTO diagnosis_versions"
                " (workshop_id, work_order_id, version_no, text, employee_id)"
                " VALUES (:w, :o, 1, 'De otra orden', :e) RETURNING id"
            ),
            {"w": quotes.order.workshop_id, "o": other, "e": quotes.admin},
        )
    with pytest.raises(DBAPIError, match="fk_quotes_diagnosis_version_same_order"):
        async with engines.app.begin() as conn:
            await set_workshops(conn, quotes.order.workshop_id)
            await conn.execute(
                text("UPDATE quotes SET diagnosis_version_id = :d WHERE id = :q"),
                {"d": foreign, "q": quotes.draft},
            )


# --- Decisiones (RF-34 a RF-36) ------------------------------------------------------

DECIDE = (
    "INSERT INTO quote_decisions"
    " (workshop_id, quote_id, outcome, channel, recorded_by_employee_id, decided_at)"
    " VALUES (:w, :q, :outcome, 'phone', :e, :at) RETURNING decided_at"
)


@pytest.mark.asyncio
async def test_a_decision_and_its_status_are_written_together(
    engines: Engines, quotes: Quotes
) -> None:
    async with engines.app.begin() as conn:
        await set_workshops(conn, quotes.order.workshop_id)
        decided_at = await conn.scalar(
            text(DECIDE),
            {
                "w": quotes.order.workshop_id,
                "q": quotes.sent,
                "outcome": "approved",
                "e": quotes.admin,
                # Antedatarla no sirve: la hora la pone la base de datos.
                "at": datetime(2000, 1, 1, tzinfo=UTC),
            },
        )
        await conn.execute(
            text("UPDATE quotes SET status = 'approved' WHERE id = :q"),
            {"q": quotes.sent},
        )
    assert decided_at.year >= 2026


@pytest.mark.asyncio
async def test_a_decision_without_its_status_fails_on_commit(
    engines: Engines, quotes: Quotes
) -> None:
    """Diferido, como el invariante 5: el error salta al confirmar, así que el
    `pytest.raises` envuelve la transacción entera."""
    with pytest.raises(DBAPIError, match="its status does not say so"):
        async with engines.app.begin() as conn:
            await set_workshops(conn, quotes.order.workshop_id)
            await conn.execute(
                text(DECIDE),
                {
                    "w": quotes.order.workshop_id,
                    "q": quotes.sent,
                    "outcome": "rejected",
                    "e": quotes.admin,
                    "at": None,
                },
            )


@pytest.mark.asyncio
async def test_the_status_must_match_the_decision(
    engines: Engines, quotes: Quotes
) -> None:
    with pytest.raises(DBAPIError, match="needs its decision to be approved"):
        async with engines.app.begin() as conn:
            await set_workshops(conn, quotes.order.workshop_id)
            await conn.execute(
                text(DECIDE),
                {
                    "w": quotes.order.workshop_id,
                    "q": quotes.sent,
                    "outcome": "rejected",
                    "e": quotes.admin,
                    "at": None,
                },
            )
            await conn.execute(
                text("UPDATE quotes SET status = 'approved' WHERE id = :q"),
                {"q": quotes.sent},
            )


@pytest.mark.asyncio
async def test_a_draft_or_an_expired_quote_cannot_be_decided(
    engines: Engines, quotes: Quotes
) -> None:
    params = {
        "w": quotes.order.workshop_id,
        "outcome": "approved",
        "e": quotes.admin,
        "at": None,
    }
    with pytest.raises(DBAPIError, match="only a sent quote can be decided"):
        async with engines.app.begin() as conn:
            await set_workshops(conn, quotes.order.workshop_id)
            await conn.execute(text(DECIDE), {**params, "q": quotes.draft})
    # Pasada su validez, aunque nadie la haya marcado como caducada (no hay
    # worker hasta F5): la hora del servidor manda.
    async with engines.owner.begin() as conn:
        await set_workshops(conn, quotes.order.workshop_id)
        await conn.execute(
            text("ALTER TABLE quotes DISABLE TRIGGER quotes_frozen_after_send")
        )
        await conn.execute(
            text("UPDATE quotes SET valid_until = clock_timestamp() WHERE id = :q"),
            {"q": quotes.sent},
        )
        await conn.execute(
            text("ALTER TABLE quotes ENABLE TRIGGER quotes_frozen_after_send")
        )
    with pytest.raises(DBAPIError, match="has expired"):
        async with engines.app.begin() as conn:
            await set_workshops(conn, quotes.order.workshop_id)
            await conn.execute(text(DECIDE), {**params, "q": quotes.sent})


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform"])
@pytest.mark.parametrize(
    "statement",
    ["UPDATE quote_decisions SET outcome = 'rejected'", "DELETE FROM quote_decisions"],
)
async def test_r5_decisions_are_append_only_also_for_the_platform(
    engines: Engines, quotes: Quotes, role: str, statement: str
) -> None:
    async with engines.app.begin() as conn:
        await set_workshops(conn, quotes.order.workshop_id)
        await conn.execute(
            text(DECIDE),
            {
                "w": quotes.order.workshop_id,
                "q": quotes.sent,
                "outcome": "approved",
                "e": quotes.admin,
                "at": None,
            },
        )
        await conn.execute(
            text("UPDATE quotes SET status = 'approved' WHERE id = :q"),
            {"q": quotes.sent},
        )
    with pytest.raises(DBAPIError, match="permission denied"):
        await as_role(engines_by_role(engines)[role], quotes, statement)


@pytest.mark.asyncio
async def test_a_phone_decision_says_who_recorded_it_and_has_no_ip(
    engines: Engines, quotes: Quotes
) -> None:
    for statement, constraint in (
        (
            (
                "INSERT INTO quote_decisions (workshop_id, quote_id, outcome, channel)"
                " VALUES (:w, :sent, 'approved', 'phone')"
            ),
            "ck_quote_decisions_recorded_by",
        ),
        (
            (
                "INSERT INTO quote_decisions (workshop_id, quote_id, outcome, channel,"
                " recorded_by_employee_id, ip) VALUES (:w, :sent, 'approved', 'phone',"
                " :e, '10.0.0.1')"
            ),
            "ck_quote_decisions_portal_only_fields",
        ),
    ):
        with pytest.raises(DBAPIError, match=constraint):
            await as_role(engines.app, quotes, statement)


# --- Concurrencia ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_line_added_while_the_quote_is_being_sent_waits_and_is_refused(
    engines: Engines, quotes: Quotes
) -> None:
    """El trigger de las líneas bloquea la versión antes de mirar su estado.
    Sin el bloqueo, la segunda leería "borrador" (el envío aún no se ha
    confirmado) y la línea entraría en una versión ya enviada, con un total que
    no la cuenta. Comprobado que falla sin el `FOR NO KEY UPDATE`."""
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE quotes SET status = 'superseded' WHERE id = :q"),
            {"q": quotes.sent},
        )
    order = quotes.order
    async with engines.app.connect() as first, engines.app.connect() as second:
        await first.begin()
        await set_workshops(first, order.workshop_id)
        await send(first, quotes.draft, quotes.admin)

        async def add() -> None:
            await second.begin()
            await set_workshops(second, order.workshop_id)
            await add_line(second, order, quotes.draft, position=2)

        work = asyncio.create_task(add())
        await asyncio.sleep(GRACE)
        assert not work.done(), "la línea debería esperar al envío"
        await first.commit()
        with pytest.raises(DBAPIError, match="is not a draft: its lines are frozen"):
            await asyncio.wait_for(work, timeout=10)
        await second.rollback()
    async with engines.platform.connect() as conn:
        lines = await conn.scalar(
            text("SELECT count(*) FROM quote_lines WHERE quote_id = :q"),
            {"q": quotes.draft},
        )
    assert lines == 1
