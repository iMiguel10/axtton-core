"""Pruebas adversas del cierre de F3 que faltaban (arquitectura §2, §3, §4, §7.1).

- Aislamiento: enviar, anular, renovar y decidir desde otro taller (las pruebas
  de F3 solo cubrían ver, crear, guardar y descartar), y archivar una tarifa
  ajena.
- Importes ocultos al mecánico: un barrido de todo lo que puede leer, también
  con una versión enviada y decidida (la prueba existente usa un borrador).
- Carreras con dos transacciones reales que no tenían prueba: decidir y anular,
  dos renovaciones, descartar a la vez que se envía, se guarda o se descarta, y
  dos ediciones de los ajustes del taller.
- Invariante 6 sobre las columnas nuevas (0014quotepdf) y lo que se cuela con
  un cambio de estado; la decisión frente al dueño de las tablas.
- La anulación de una versión ya marcada como caducada (lo que escribirá el
  worker en F5).
"""

import asyncio
import traceback
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core.errors import ConflictError, NotFoundError
from app.domain.quotes import DecisionChannel, Outcome
from app.infra.email import InMemoryEmailSender
from tests.conftest import Engines, TwoWorkshops
from tests.test_clients import open_workshop
from tests.test_concurrency import (
    GRACE,
    MakeAccount,
    dispose_global_engines,  # noqa: F401
    employee_with_access,
    open_transaction,
)
from tests.test_employees import add_mechanic, invite_and_accept
from tests.test_quote_decision import decide, sent_order, sent_quote
from tests.test_quote_send import (
    cancel,
    diagnosing_order,
    draft_with_lines,
    order_of,
    send,
    sendable_draft,
    version_of,
)
from tests.test_quotes import ORDERS, QUOTES, create, quotes_of, save
from tests.test_quotes_db import Quotes, as_role, engines_by_role, quotes
from tests.test_rls import set_workshops
from tests.test_settings import RATES, add_rate
from tests.test_work_orders import Shop, outbox, shop
from tests.test_work_orders_db import seed_order

__all__ = ["outbox", "quotes", "shop"]

SETTINGS = "/api/v1/workshop/settings"


async def outcome_of(session: AsyncSession, work: "asyncio.Task[Any]") -> object:
    """Como `finish` de test_concurrency.py, pero devuelve CUALQUIER excepción
    en vez de dejarla escapar: así una carrera que acaba en un AssertionError
    (lo que la API convierte en un 500) se ve en la aserción, no como un error
    de la prueba."""
    try:
        result = await asyncio.wait_for(work, timeout=10)
    except Exception as error:  # noqa: BLE001 - es lo que se quiere mirar
        await session.rollback()
        return error
    await session.commit()
    return result


def where(outcome: object) -> str:
    """Lo que salió y, si fue una excepción, dónde: un AssertionError sin texto
    no dice nada sin su última línea de la aplicación."""
    if isinstance(outcome, BaseException):
        frames = traceback.extract_tb(outcome.__traceback__)
        own = [f for f in frames if "/app/app/" in f.filename] or frames
        last = own[-1]
        return f"{outcome!r} en {last.filename}:{last.lineno} ({last.line})"
    return repr(outcome)


async def statuses(engines: Engines, order_id: UUID) -> list[str]:
    async with engines.platform.connect() as conn:
        rows = await conn.scalars(
            text(
                "SELECT status FROM quotes WHERE work_order_id = :o ORDER BY version_no"
            ),
            {"o": order_id},
        )
        return list(rows)


async def order_status(engines: Engines, order_id: UUID) -> str:
    async with engines.platform.connect() as conn:
        status: str = await conn.scalar(
            text("SELECT status FROM work_orders WHERE id = :o"), {"o": order_id}
        )
    return status


# --- Aislamiento: las acciones de F3 desde otro taller ----------------------------


@pytest.mark.asyncio
async def test_sending_cancelling_renewing_or_deciding_from_another_workshop_is_a_404(
    client: AsyncClient, shop: Shop
) -> None:
    """RNF-01 en las acciones que cambian el estado: desde B, la versión de A no
    existe (404, no 403 ni 409) y nada cambia. Después, las mismas peticiones
    desde A funcionan: el 404 era el aislamiento, no un id o un cuerpo
    inválidos."""
    order_id = await diagnosing_order(client, shop)
    draft = await draft_with_lines(client, shop, order_id)
    waiting_order, waiting = await sent_order(client, shop)
    other = await open_workshop(client, "Talleres Gómez")

    draft_version = await version_of(client, shop, order_id, draft)
    waiting_version = await version_of(client, shop, waiting_order, waiting)
    attempts = {
        "send": (f"{QUOTES}/{draft}/send", {"version": draft_version}),
        "cancel": (
            f"{QUOTES}/{waiting}/cancel",
            {"version": waiting_version, "reason": "Desde otro taller"},
        ),
        "renew": (f"{QUOTES}/{waiting}/renew", {"version": waiting_version}),
        "decision": (
            f"{QUOTES}/{waiting}/decision",
            {"version": waiting_version, "outcome": "approved", "channel": "phone"},
        ),
    }
    for name, (url, body) in attempts.items():
        response = await client.post(url, json=body, headers=other.headers)
        assert (response.status_code, response.json().get("code")) == (
            404,
            "quote_not_found",
        ), (name, response.text)

    (still_draft,) = await quotes_of(client, shop.headers, order_id)
    assert (still_draft["status"], still_draft["version"]) == ("draft", draft_version)
    (still_waiting,) = await quotes_of(client, shop.headers, waiting_order)
    assert (still_waiting["status"], still_waiting["version"]) == (
        "sent",
        waiting_version,
    )
    assert still_waiting["decision"] is None
    assert (await order_of(client, shop, waiting_order))["status"] == (
        "pending_approval"
    )

    # Control: desde A, lo mismo sí se aplica.
    url, body = attempts["send"]
    assert (await client.post(url, json=body, headers=shop.headers)).status_code == 204
    url, body = attempts["decision"]
    assert (await client.post(url, json=body, headers=shop.headers)).status_code == 204


@pytest.mark.asyncio
async def test_a_rate_of_another_workshop_cannot_be_archived_or_unarchived(
    client: AsyncClient, shop: Shop
) -> None:
    """La prueba de las tarifas ajenas solo miraba el PATCH."""
    rate_id = await add_rate(client, shop.admin, "Mecánica", 4500)
    other = await open_workshop(client, "Talleres Gómez")
    for action in ("archive", "unarchive"):
        response = await client.post(
            f"{RATES}/{rate_id}/{action}", json={"version": 1}, headers=other.headers
        )
        assert (response.status_code, response.json().get("code")) == (
            404,
            "labor_rate_not_found",
        ), (action, response.text)
    listed = await client.get(RATES, headers=shop.headers)
    assert [(r["id"], r["version"]) for r in listed.json()] == [(rate_id, 1)]


# --- El mecánico sin importes: ningún importe en nada de lo que puede leer --------

PRICED = {
    "kind": "labor",
    "description": "Cambio de embrague",
    "quantity": "1",
    "unit_price_cents": 12345,
    "vat_bp": 2100,
}


def integers_in(value: Any) -> set[int]:
    if isinstance(value, bool):
        return set()
    if isinstance(value, int):
        return {value}
    if isinstance(value, dict):
        return set().union(*(integers_in(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(integers_in(v) for v in value))
    return set()


@pytest.mark.asyncio
async def test_a_mechanic_who_cannot_see_prices_finds_no_amount_anywhere(
    client: AsyncClient, shop: Shop, outbox: InMemoryEmailSender
) -> None:
    """Especificación §3: con `mechanics_see_sale_prices` desactivado, ninguna
    ruta que el mecánico puede leer le enseña un importe de venta. Con una
    versión decidida y otra en borrador, con descuento global en importe."""
    mechanic = await invite_and_accept(
        client, shop.admin, outbox, await add_mechanic(client, shop.admin)
    )
    order_id = await diagnosing_order(client, shop)
    first = await create(client, shop.headers, order_id)
    saved = await save(
        client,
        shop.headers,
        first,
        1,
        [PRICED],
        global_discount={"kind": "amount", "value": 345},
    )
    assert saved.status_code == 200, saved.text
    assert (await send(client, shop, order_id, first)).status_code == 204
    assert (await decide(client, shop, order_id, first)).status_code == 204
    await create(client, shop.headers, order_id)  # un borrador, copia de la 1

    # Los importes, tal como los ve el administrador.
    amounts: set[int] = set()
    for quote in await quotes_of(client, shop.headers, order_id):
        amounts |= {quote["global_discount_value"]}
        amounts |= integers_in(quote["totals"])
        for line in quote["lines"]:
            amounts |= {line["unit_price_cents"], line["taxable_cents"]}
            amounts |= {line["total_cents"]}
    amounts -= {None, 0, 2100}  # 2100 es también el tipo de IVA en puntos básicos
    assert {12345, 345, 12000, 14520} <= amounts  # control: los hay

    current = await client.get(SETTINGS, headers=shop.headers)
    hidden = await client.patch(
        SETTINGS,
        json={"version": current.json()["version"], "mechanics_see_sale_prices": False},
        headers=shop.headers,
    )
    assert hidden.status_code == 204, hidden.text

    readable = [
        f"{ORDERS}/{order_id}/quotes",
        f"{ORDERS}/{order_id}",
        ORDERS,
        f"{QUOTES}?view=all",
        f"{QUOTES}?view=drafts",
        f"{ORDERS}/unpaid",
    ]
    leaks = {}
    for url in readable:
        response = await client.get(url, headers=mechanic)
        assert response.status_code == 200, (url, response.text)
        found = integers_in(response.json()) & amounts
        if found:
            leaks[url] = found
    assert leaks == {}
    for quote in await quotes_of(client, mechanic, order_id):
        assert quote["prices_hidden"] is True
        pdf = await client.get(f"{QUOTES}/{quote['id']}/pdf", headers=mechanic)
        assert (pdf.status_code, pdf.json()["code"]) == (403, "quote_prices_hidden")


# --- El PDF: lo que llega de los datos es texto, nunca HTML -----------------------


@pytest.mark.asyncio
async def test_markup_written_in_a_quote_comes_out_as_text_in_its_pdf(
    client: AsyncClient, shop: Shop
) -> None:
    """La primera defensa del PDF (infra/pdf.py) es el autoescape de Jinja: una
    descripción con etiquetas sale tal cual, como texto. Sin él, quien prepara
    el presupuesto podría ocultar líneas o pintar un "Aceptado" falso en un
    documento con valor legal, o pedir recursos (que el fetcher ya rechaza)."""
    from tests.test_quote_pdf import pdf, text_of

    order_id = await diagnosing_order(client, shop)
    quote_id = await create(client, shop.headers, order_id)
    line = {
        **PRICED,
        "description": '<b>Negrita</b><span style="display:none">OCULTO</span>',
        "reference": "<i>REF</i>",
    }
    saved = await save(client, shop.headers, quote_id, 1, [line])
    assert saved.status_code == 200, saved.text
    content = text_of(await pdf(client, shop.headers, quote_id))
    assert "<b>Negrita</b>" in content
    assert 'style="display:none"' in content
    assert "<i>REF</i>" in content


@pytest.mark.asyncio
async def test_rf15_an_anonymized_client_leaves_nothing_in_its_quotes_or_their_pdf(
    client: AsyncClient, shop: Shop, engines: Engines
) -> None:
    """El barrido de RNF-40 (test_anonymize.py) anonimiza a un cliente sin
    presupuestos. Con una versión aprobada (con `vehicle_snapshot`, líneas,
    decisión y auditoría de F3), tampoco queda nada suyo en ninguna tabla, y el
    PDF, que lee el nombre al generarse, dice "Cliente eliminado"."""
    from tests.test_anonymize import CLIENTS, PERSONAL, anonymize, read
    from tests.test_quote_decision import deliver
    from tests.test_quote_pdf import pdf, text_of

    patched = await client.patch(
        f"{CLIENTS}/{shop.maria['id']}",
        json={"version": shop.maria["version"], **PERSONAL},
        headers=shop.headers,
    )
    assert patched.status_code == 204, patched.text
    order_id, quote_id = await sent_order(client, shop)
    assert (await decide(client, shop, order_id, quote_id)).status_code == 204
    before = text_of(await pdf(client, shop.headers, quote_id))
    assert PERSONAL["name"] in before  # control: el PDF lo llevaba
    await deliver(order_id)

    maria = await read(client, shop.headers, shop.maria["id"])
    assert (await anonymize(client, shop.headers, maria)).status_code == 204

    after = text_of(await pdf(client, shop.headers, quote_id))
    assert "Cliente eliminado" in after
    assert [v for v in PERSONAL.values() if v in after] == []
    async with engines.platform.connect() as conn:
        tables = (
            await conn.scalars(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                    " AND has_table_privilege("
                    "quote_ident(schemaname) || '.' || quote_ident(tablename),"
                    " 'SELECT')"
                )
            )
        ).all()
        assert {"quotes", "quote_lines", "quote_decisions"} <= set(tables)
        dump = "\n".join(
            [
                row
                for table in tables
                for row in (
                    await conn.scalars(text(f'SELECT t::text FROM "{table}" t'))
                ).all()
            ]
        ).lower()
    assert [v for v in PERSONAL.values() if v.lower() in dump] == []


# --- Carreras con dos transacciones reales ----------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("first_action", ["decide", "cancel"])
async def test_a_decision_and_a_cancellation_at_once_never_both_apply(
    engines: Engines,
    two_workshops: TwoWorkshops,
    make_account: MakeAccount,
    first_action: str,
) -> None:
    """Decidir y anular la misma versión piden los dos la orden con FOR UPDATE:
    la segunda espera y se encuentra la versión cambiada (409). Nunca queda una
    versión anulada con su decisión, ni una aprobada con la orden devuelta a su
    origen."""
    from app.services import quotes as quote_service

    order, staff, quote_id, version = await sent_quote(
        engines, two_workshops, make_account
    )
    a = order.workshop_id

    async def decide_it(session: AsyncSession) -> None:
        return await quote_service.record_decision(
            session,
            a,
            staff.user_id,
            staff.employee_id,
            quote_id,
            expected_version=version,
            outcome=Outcome.APPROVED,
            channel=DecisionChannel.PHONE,
            note=None,
        )

    async def cancel_it(session: AsyncSession) -> None:
        return await quote_service.cancel_quote(
            session,
            a,
            staff.user_id,
            staff.employee_id,
            quote_id,
            expected_version=version,
            reason="El cliente se lo ha pensado",
        )

    actions: dict[str, Callable[[AsyncSession], Coroutine[Any, Any, None]]] = {
        "decide": decide_it,
        "cancel": cancel_it,
    }
    second_action = "cancel" if first_action == "decide" else "decide"
    async with open_transaction(a) as first, open_transaction(a) as second:
        await actions[first_action](first)
        work = asyncio.create_task(actions[second_action](second))
        await asyncio.sleep(GRACE)
        assert not work.done(), "la segunda debería esperar a la orden"
        await first.commit()
        outcome = await outcome_of(second, work)

    assert isinstance(outcome, ConflictError), outcome
    async with engines.platform.connect() as conn:
        decisions = await conn.scalar(
            text("SELECT count(*) FROM quote_decisions WHERE quote_id = :q"),
            {"q": quote_id},
        )
    if first_action == "decide":
        assert (await statuses(engines, order.order_id), decisions) == (["approved"], 1)
        assert await order_status(engines, order.order_id) == "approved"
    else:
        assert (await statuses(engines, order.order_id), decisions) == (
            ["cancelled"],
            0,
        )
        assert await order_status(engines, order.order_id) == "diagnosing"


@pytest.mark.asyncio
async def test_two_renewals_of_the_same_version_at_once_leave_one_new_version(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """Dos personas amplían el plazo de la misma versión: la segunda espera a la
    orden, ve la renovada ya sustituida y recibe un 409. Queda una sola versión
    nueva, no dos (ni un 500 al chocar con el índice de `sent`)."""
    from app.services import quotes as quote_service

    order, staff, quote_id, version = await sent_quote(
        engines, two_workshops, make_account
    )
    a = order.workshop_id

    async def renew_it(session: AsyncSession) -> UUID:
        return await quote_service.renew_quote(
            session,
            a,
            staff.user_id,
            staff.employee_id,
            quote_id,
            expected_version=version,
        )

    async with open_transaction(a) as first, open_transaction(a) as second:
        await renew_it(first)
        work = asyncio.create_task(renew_it(second))
        await asyncio.sleep(GRACE)
        assert not work.done(), "la segunda renovación debería esperar"
        await first.commit()
        outcome = await outcome_of(second, work)

    assert isinstance(outcome, ConflictError), outcome
    assert await statuses(engines, order.order_id) == ["superseded", "sent"]


@pytest.mark.asyncio
@pytest.mark.parametrize("first_action", ["decide", "send"])
async def test_a_correction_sent_while_the_previous_version_is_decided_never_both_apply(
    engines: Engines,
    two_workshops: TwoWorkshops,
    make_account: MakeAccount,
    first_action: str,
) -> None:
    """La v1 espera respuesta y alguien envía su corrección (v2) mientras otro
    registra que el cliente aprobó la v1: son dos filas de `quotes` distintas,
    así que el bloqueo de la versión no las pone en fila; solo el de la orden.
    El segundo tiene que recibir el 409 del service (lo ha visto todo), no el
    StaleDataError del ORM al tropezar con la versión ajena."""
    from app.services import quotes as quote_service

    order, staff, v1, version = await sent_quote(engines, two_workshops, make_account)
    a = order.workshop_id
    async with open_transaction(a) as session:
        v2 = await quote_service.create_draft(
            session, a, staff.employee_id, order.order_id
        )
        await session.commit()

    async def decide_v1(session: AsyncSession) -> None:
        return await quote_service.record_decision(
            session,
            a,
            staff.user_id,
            staff.employee_id,
            v1,
            expected_version=version,
            outcome=Outcome.APPROVED,
            channel=DecisionChannel.PHONE,
            note=None,
        )

    async def send_v2(session: AsyncSession) -> None:
        return await quote_service.send_quote(
            session, a, staff.user_id, staff.employee_id, v2, expected_version=1
        )

    actions: dict[str, Callable[[AsyncSession], Coroutine[Any, Any, None]]] = {
        "decide": decide_v1,
        "send": send_v2,
    }
    second_action = "send" if first_action == "decide" else "decide"
    async with open_transaction(a) as first, open_transaction(a) as second:
        await actions[first_action](first)
        work = asyncio.create_task(actions[second_action](second))
        await asyncio.sleep(GRACE)
        assert not work.done(), "la segunda debería esperar a la orden"
        await first.commit()
        outcome = await outcome_of(second, work)

    assert isinstance(outcome, ConflictError), where(outcome)
    if first_action == "decide":
        assert await statuses(engines, order.order_id) == ["approved", "draft"]
        assert await order_status(engines, order.order_id) == "approved"
    else:
        assert await statuses(engines, order.order_id) == ["superseded", "sent"]
        assert await order_status(engines, order.order_id) == "pending_approval"


async def _discard(session: AsyncSession, a: UUID, quote_id: UUID, *_: Any) -> None:
    from app.services import quotes as quote_service

    await quote_service.discard_draft(session, quote_id, expected_version=1)


async def _send(session: AsyncSession, a: UUID, quote_id: UUID, staff: Any) -> None:
    from app.services import quotes as quote_service

    await quote_service.send_quote(
        session, a, staff.user_id, staff.employee_id, quote_id, expected_version=1
    )


async def _save(session: AsyncSession, a: UUID, quote_id: UUID, *_: Any) -> None:
    from decimal import Decimal

    from app.domain.quotes import LineKind
    from app.services import quotes as quote_service
    from app.services.quotes import LineInput

    line = LineInput(LineKind.OTHER, "Otra cosa", None, None, Decimal(1), 500, 0, 2100)
    await quote_service.save_draft(
        session,
        a,
        quote_id,
        expected_version=1,
        global_discount=None,
        lines=[line],
        delivery_business_days=5,
    )


DRAFT_ACTIONS = {"discard": _discard, "send": _send, "save": _save}


@pytest.mark.asyncio
async def test_a_draft_sent_while_it_is_being_discarded_waits_and_is_refused_by_the_discard(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """Enviar primero: el descarte espera a la orden y se encuentra la versión
    enviada (409 `quote_not_draft`). La enviada sigue entera."""
    order = await seed_order(engines, two_workshops)
    a = order.workshop_id
    staff = await employee_with_access(engines, make_account, a, "admin")
    quote_id = await sendable_draft(engines, a, order.order_id)

    async with open_transaction(a) as first, open_transaction(a) as second:
        await _send(first, a, quote_id, staff)
        work = asyncio.create_task(_discard(second, a, quote_id))
        await asyncio.sleep(GRACE)
        assert not work.done(), "el descarte debería esperar al envío"
        await first.commit()
        outcome = await outcome_of(second, work)

    assert isinstance(outcome, ConflictError), outcome
    assert outcome.code == "quote_not_draft"
    assert await statuses(engines, order.order_id) == ["sent"]


@pytest.mark.asyncio
@pytest.mark.parametrize("second_action", ["send", "save", "discard"])
async def test_what_comes_after_a_discard_of_the_same_draft_is_a_client_error(
    engines: Engines,
    two_workshops: TwoWorkshops,
    make_account: MakeAccount,
    second_action: str,
) -> None:
    """Descartar primero (dos pestañas, un doble clic): lo que espera detrás a
    la versión la encuentra borrada. Tiene que ser un 404 o un 409, nunca un
    500, y el borrador no debe resucitar."""
    order = await seed_order(engines, two_workshops)
    a = order.workshop_id
    staff = await employee_with_access(engines, make_account, a, "admin")
    quote_id = await sendable_draft(engines, a, order.order_id)

    async with open_transaction(a) as first, open_transaction(a) as second:
        await _discard(first, a, quote_id)
        work = asyncio.create_task(
            DRAFT_ACTIONS[second_action](second, a, quote_id, staff)
        )
        await asyncio.sleep(GRACE)
        assert not work.done(), "la segunda debería esperar al descarte"
        await first.commit()
        outcome = await outcome_of(second, work)

    assert isinstance(outcome, NotFoundError | ConflictError), where(outcome)
    assert await statuses(engines, order.order_id) == []
    assert await order_status(engines, order.order_id) == "diagnosing"


@pytest.mark.asyncio
async def test_two_admins_editing_the_workshop_settings_at_once_keep_one_change(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """RNF-15 en los ajustes del taller: el service no bloquea la fila, así que
    lo único que para al segundo es la `version` que vigila SQLAlchemy. El
    segundo UPDATE espera a la fila, ya no la encuentra con su versión y recibe
    un 409 (StaleDataError). Queda el cambio del primero y una sola auditoría."""
    from app.services import settings as settings_service

    a = two_workshops.a
    ana = await employee_with_access(engines, make_account, a, "admin")
    luis = await employee_with_access(engines, make_account, a, "admin")

    async with open_transaction(a) as first, open_transaction(a) as second:
        await settings_service.update_workshop(
            first,
            a,
            ana.user_id,
            expected_version=1,
            changes={"quote_validity_business_days": 30},
        )
        work = asyncio.create_task(
            settings_service.update_workshop(
                second,
                a,
                luis.user_id,
                expected_version=1,
                changes={"quote_validity_business_days": 15, "phone": "900 000 000"},
            )
        )
        await asyncio.sleep(GRACE)
        assert not work.done(), "el segundo debería esperar a la fila del taller"
        await first.commit()
        outcome = await outcome_of(second, work)

    assert isinstance(outcome, StaleDataError | ConflictError), repr(outcome)
    async with engines.platform.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT quote_validity_business_days, phone, version"
                    " FROM workshops WHERE id = :w"
                ),
                {"w": a},
            )
        ).one()
        audits = await conn.scalar(
            text(
                "SELECT count(*) FROM audit_log WHERE workshop_id = :w"
                " AND action = 'workshop_settings_updated'"
            ),
            {"w": a},
        )
    assert tuple(row) == (30, None, 2)
    assert audits == 1


# --- Invariante 6: lo que no cambia, con cualquier rol ----------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform", "owner"])
@pytest.mark.parametrize(
    "statement",
    [
        # Columnas de 0014quotepdf, sobre las que axtton_app tiene UPDATE.
        """UPDATE quotes SET vehicle_snapshot = '{"plate": "0000 XXX"}' WHERE id = :sent""",
        "UPDATE quotes SET delivery_business_days = 99 WHERE id = :sent",
        # Las del envío que la aplicación también puede escribir.
        "UPDATE quotes SET sent_at = sent_at - interval '30 days' WHERE id = :sent",
        "UPDATE quotes SET origin_status = 'in_repair' WHERE id = :sent",
        "UPDATE quotes SET valid_until = valid_until + interval '1 day' WHERE id = :sent",
        # Un cambio de contenido colado junto a un cambio de estado permitido.
        (
            "UPDATE quotes SET status = 'cancelled', cancel_reason = 'x',"
            " delivery_business_days = 99 WHERE id = :sent"
        ),
        (
            "UPDATE quotes SET status = 'superseded',"
            """ vehicle_snapshot = '{"plate": "0000 XXX"}' WHERE id = :sent"""
        ),
    ],
)
async def test_r6_what_was_sent_does_not_change_with_any_role_even_with_a_status_change(
    engines: Engines, quotes: Quotes, role: str, statement: str
) -> None:
    with pytest.raises(DBAPIError, match="was sent: it cannot change"):
        await as_role(engines_by_role(engines)[role], quotes, statement)


@pytest_asyncio.fixture
async def decided(engines: Engines, quotes: Quotes) -> Quotes:
    """La versión enviada de `quotes`, aprobada por teléfono."""
    async with engines.platform.begin() as conn:
        await set_workshops(conn, quotes.order.workshop_id)
        await conn.execute(
            text(
                "INSERT INTO quote_decisions (workshop_id, quote_id, outcome, channel,"
                " recorded_by_employee_id) VALUES (:w, :q, 'approved', 'phone', :e)"
            ),
            {"w": quotes.order.workshop_id, "q": quotes.sent, "e": quotes.admin},
        )
        await conn.execute(
            text("UPDATE quotes SET status = 'approved' WHERE id = :q"),
            {"q": quotes.sent},
        )
    return quotes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE quotes SET delivery_business_days = 99 WHERE id = :sent",
        "UPDATE quotes SET status = 'cancelled', cancel_reason = 'x' WHERE id = :sent",
    ],
)
async def test_an_approved_quote_does_not_change_even_for_the_owner(
    engines: Engines, decided: Quotes, statement: str
) -> None:
    with pytest.raises(DBAPIError, match="was sent: it cannot change|cannot go from"):
        await as_role(engines.owner, decided, statement)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE quote_decisions SET outcome = 'rejected' WHERE quote_id = :sent",
        (
            "UPDATE quote_decisions SET decided_at = decided_at - interval '1 year'"
            " WHERE quote_id = :sent"
        ),
        "DELETE FROM quote_decisions WHERE quote_id = :sent",
    ],
)
async def test_a_decision_does_not_change_even_for_the_owner(
    engines: Engines, decided: Quotes, statement: str
) -> None:
    """Invariante 6: los permisos lo impiden a la aplicación y a la plataforma;
    al dueño, el trigger quote_decisions_frozen (0015decisionsfrozen)."""
    with pytest.raises(DBAPIError, match="cannot change"):
        await as_role(engines.owner, decided, statement)


# --- Anular una versión ya marcada como caducada (F5 la marcará) -----------------


@pytest.mark.asyncio
async def test_cancelling_a_version_marked_expired_returns_the_order_to_its_origin(
    client: AsyncClient, shop: Shop, engines: Engines
) -> None:
    """Especificación §6: caducado, "el taller envía una versión nueva o la
    anula". Anularla tiene que dejar la orden igual que anular una enviada fuera
    de plazo que nadie ha marcado (test_a_quote_past_its_validity_says_so): de
    vuelta a su estado de origen."""
    order_id, quote_id = await sent_order(client, shop)
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE quotes SET status = 'expired' WHERE id = :q"), {"q": quote_id}
        )
    response = await cancel(client, shop, order_id, quote_id)
    assert response.status_code == 204, response.text
    assert (await order_of(client, shop, order_id))["status"] == "diagnosing"
