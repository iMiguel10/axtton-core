"""El worker marca como caducadas las versiones fuera de plazo (F5 paso 2, RF-33).

Hasta F5 la caducidad se decidía al leer (`is_expired`), así que marcarla no
cambia lo que se ve ni lo que se puede hacer: lo que se comprueba aquí es eso,
que solo se marca lo que ya estaba fuera de plazo (también con SQL, por un
trigger) y que una carrera con el taller no deja nada a medias.
"""

import asyncio
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.domain.quotes import QuoteStatus
from app.jobs.context import WorkerContext
from app.jobs.quotes import expire_quotes
from app.platform.scheduler import workshops_with_overdue_quotes
from app.services import quotes as quote_service
from tests.conftest import Engines, TwoWorkshops
from tests.test_concurrency import (
    GRACE,
    MakeAccount,
    dispose_global_engines,  # noqa: F401 (autouse)
    finish,
    open_transaction,
)
from tests.test_quote_decision import decide, sent_order, sent_quote
from tests.test_quote_pdf import pdf
from tests.test_quote_send import cancel, order_of
from tests.test_quotes import expire_by_sql, quotes_of
from tests.test_rls import set_workshops
from tests.test_work_orders import Shop, outbox, shop

__all__ = ["outbox", "shop"]

NO_CONTEXT = cast(WorkerContext, {})


async def status_of(engines: Engines, quote_id: object) -> str:
    async with engines.platform.connect() as conn:
        status = await conn.scalar(
            text("SELECT status FROM quotes WHERE id = :q"), {"q": quote_id}
        )
    assert isinstance(status, str)
    return status


@pytest.mark.asyncio
async def test_only_overdue_versions_are_marked_and_nothing_else_changes(
    client: AsyncClient, shop: Shop, engines: Engines
) -> None:
    overdue_order, overdue = await sent_order(client, shop)
    _, valid = await sent_order(client, shop)
    await expire_by_sql(overdue)
    order_before = await order_of(client, shop, overdue_order)
    pdf_before = (await pdf(client, shop.headers, overdue)).content

    assert await expire_quotes(NO_CONTEXT) == 1
    assert await status_of(engines, overdue) == "expired"
    assert await status_of(engines, valid) == "sent"
    # Otra pasada no encuentra nada: ejecutarla dos veces es inocuo.
    assert await expire_quotes(NO_CONTEXT) == 0

    # La orden no cambia (especificación §6): sigue esperando respuesta.
    order_after = await order_of(client, shop, overdue_order)
    assert order_after["status"] == order_before["status"] == "pending_approval"
    assert order_after["version"] == order_before["version"]
    # El PDF ya decía "caducado" leyendo la validez: sale idéntico (RF-55).
    assert (await pdf(client, shop.headers, overdue)).content == pdf_before
    (quote,) = await quotes_of(client, shop.headers, overdue_order)
    assert (quote["status"], quote["expired"]) == ("expired", True)


@pytest.mark.asyncio
async def test_a_marked_version_answers_as_before(
    client: AsyncClient, shop: Shop
) -> None:
    """Decidir da el mismo 409 que antes de marcarla, y se puede anular."""
    order_id, quote_id = await sent_order(client, shop)
    await expire_by_sql(quote_id)
    before = await decide(client, shop, order_id, quote_id)
    assert await expire_quotes(NO_CONTEXT) == 1
    after = await decide(client, shop, order_id, quote_id)
    assert (before.status_code, before.json()) == (409, {"code": "quote_expired"})
    assert (after.status_code, after.json()) == (409, {"code": "quote_expired"})

    assert (await cancel(client, shop, order_id, quote_id)).status_code == 204
    (quote,) = await quotes_of(client, shop.headers, order_id)
    assert quote["status"] == "cancelled"


@pytest.mark.asyncio
async def test_the_scheduler_only_finds_workshops_with_overdue_versions(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    order, _, quote_id, _ = await sent_quote(engines, two_workshops, make_account)
    assert await workshops_with_overdue_quotes() == []
    await expire_by_sql(str(quote_id))
    assert await workshops_with_overdue_quotes() == [order.workshop_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "owner"])
async def test_a_valid_version_cannot_be_marked_expired_by_anyone(
    engines: Engines,
    two_workshops: TwoWorkshops,
    make_account: MakeAccount,
    role: str,
) -> None:
    """Un fallo que la marcara antes de tiempo le quitaría al cliente un
    presupuesto que aún puede aceptar: el trigger lo para con cualquier rol."""
    order, _, quote_id, _ = await sent_quote(engines, two_workshops, make_account)
    async with getattr(engines, role).connect() as conn:
        await set_workshops(conn, order.workshop_id)
        with pytest.raises(DBAPIError, match="is still valid until"):
            await conn.execute(
                text("UPDATE quotes SET status = 'expired' WHERE id = :q"),
                {"q": quote_id},
            )
        await conn.rollback()
    assert await status_of(engines, quote_id) == "sent"


@pytest.mark.asyncio
async def test_a_version_valid_again_when_its_turn_comes_is_left_alone(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """Entre la búsqueda y el bloqueo, todo pudo cambiar: se vuelve a mirar con
    la versión bloqueada y la hora de la base de datos."""
    order, _, quote_id, _ = await sent_quote(engines, two_workshops, make_account)
    assert await quote_service._expire_one(order.workshop_id, quote_id) is False
    assert await status_of(engines, quote_id) == "sent"


@pytest.mark.asyncio
async def test_renewing_while_the_worker_expires_leaves_one_valid_version(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """Dos transacciones reales: el taller renueva una versión caducada (la tiene
    bloqueada) mientras el worker la iba a marcar. El worker espera al bloqueo,
    la encuentra sustituida y no hace nada."""
    order, staff, quote_id, version = await sent_quote(
        engines, two_workshops, make_account
    )
    a = order.workshop_id
    await expire_by_sql(str(quote_id))

    async with open_transaction(a) as session:
        renewed = await quote_service.renew_quote(
            session,
            a,
            staff.user_id,
            staff.employee_id,
            quote_id,
            expected_version=version,
        )
        work = asyncio.create_task(quote_service.expire_overdue(a))
        await asyncio.sleep(GRACE)
        assert not work.done()  # esperando al bloqueo de la versión
        await session.commit()
        assert await finish(session, work) == 0

    assert await status_of(engines, quote_id) == QuoteStatus.SUPERSEDED
    assert await status_of(engines, renewed) == QuoteStatus.SENT
