"""Los avisos de presupuesto al cliente (F5 paso 5, RF-60): enviado y anulado.

Nacen en la transacción del cambio (invariante 8) y su compositor vuelve a
comprobar al enviarlos que el motivo sigue vigente. Se recorre el camino de
verdad: la API del taller envía, corrige, renueva o anula, y la bandeja despacha
y entrega con los compositores reales.
"""

from typing import Any, cast
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.infra.email import InMemoryEmailSender, build_message
from app.infra.queue import InMemoryJobQueue
from app.services import notifications as notification_service
from app.services import quotes as quote_service
from app.services.notice_composers import COMPOSERS
from tests.conftest import Engines
from tests.test_concurrency import (
    dispose_global_engines,  # noqa: F401 (autouse)
    open_transaction,
)
from tests.test_quote_decision import sent_order
from tests.test_quote_send import cancel, draft_with_lines, renew, send, version_of
from tests.test_quotes import expire_by_sql, quotes_of
from tests.test_work_orders import Shop, outbox, shop

__all__ = ["outbox", "shop"]


async def workshop_of(engines: Engines, order_id: str) -> UUID:
    async with engines.platform.connect() as conn:
        found = await conn.scalar(
            text("SELECT workshop_id FROM work_orders WHERE id = :o"), {"o": order_id}
        )
    assert isinstance(found, UUID)
    return found


async def set_client(engines: Engines, shop: Shop, **values: Any) -> None:
    assignments = ", ".join(f"{column} = :{column}" for column in values)
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(f"UPDATE clients SET {assignments} WHERE id = :c"),
            {**values, "c": shop.maria["id"]},
        )


async def set_workshop(engines: Engines, workshop_id: UUID, **values: Any) -> None:
    assignments = ", ".join(f"{column} = :{column}" for column in values)
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(f"UPDATE workshops SET {assignments} WHERE id = :w"),
            {**values, "w": workshop_id},
        )


async def notices(engines: Engines) -> dict[str, dict[str, Any]]:
    """Los avisos por su `dedupe_key`."""
    async with engines.platform.connect() as conn:
        rows = (await conn.execute(text("SELECT * FROM notifications"))).mappings()
        return {row["dedupe_key"]: dict(row) for row in rows}


async def deliver_due(workshop_id: UUID) -> InMemoryEmailSender:
    """Una pasada del despachador y el envío de lo que encoló, con los
    compositores de verdad."""
    queue = InMemoryJobQueue()
    await notification_service.dispatch(workshop_id, queue, email_enabled=True)
    sender = InMemoryEmailSender()
    for job in queue.jobs:
        await notification_service.deliver(
            workshop_id,
            UUID(cast(str, job.kwargs["notification_id"])),
            cast(int, job.kwargs["attempt"]),
            sender,
            COMPOSERS,
        )
    return sender


@pytest_asyncio.fixture
async def maria_with_email(engines: Engines, shop: Shop) -> Shop:
    await set_client(engines, shop, email="maria@example.com")
    return shop


# --- Nacen con el cambio -------------------------------------------------------------


@pytest.mark.asyncio
async def test_sending_a_quote_creates_its_notice_for_the_order_s_client(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    order_id, quote_id = await sent_order(client, maria_with_email)
    notice = (await notices(engines))[f"quote_sent:{quote_id}"]
    assert (notice["kind"], notice["status"]) == ("quote_sent", "pending")
    assert str(notice["client_id"]) == maria_with_email.maria["id"]
    assert (str(notice["work_order_id"]), str(notice["quote_id"])) == (
        order_id,
        quote_id,
    )


@pytest.mark.asyncio
async def test_a_send_that_is_undone_leaves_no_notice(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    """Invariante 8: el aviso va en la transacción del envío."""
    from tests.test_quote_send import diagnosing_order

    order_id = await diagnosing_order(client, maria_with_email)
    quote_id = await draft_with_lines(client, maria_with_email, order_id)
    workshop_id = await workshop_of(engines, order_id)
    async with engines.platform.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT e.id, e.user_id FROM employees e"
                    " WHERE e.workshop_id = :w AND e.role = 'admin'"
                ),
                {"w": workshop_id},
            )
        ).one()
    version = await version_of(client, maria_with_email, order_id, quote_id)
    async with open_transaction(workshop_id) as session:
        await quote_service.send_quote(
            session,
            workshop_id,
            row.user_id,
            row.id,
            UUID(quote_id),
            expected_version=version,
        )
        await session.rollback()
    assert await notices(engines) == {}


# --- El correo ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_quote_sent_email_says_what_and_until_when(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    order_id, quote_id = await sent_order(client, maria_with_email)
    workshop_id = await workshop_of(engines, order_id)
    await set_workshop(
        engines,
        workshop_id,
        reply_to_email="taller@example.com",
        portal_slug="talleres-prueba",
    )
    sent = await deliver_due(workshop_id)

    [email] = sent.sent
    assert email.to == "maria@example.com"
    assert email.reply_to == "taller@example.com"  # RF-68
    (quote,) = await quotes_of(client, maria_with_email.headers, order_id)
    assert "121,00 €" in email.body  # 100 € más el 21 % de IVA
    assert "Es válido hasta el" in email.body
    # El botón: la entrada del portal del taller, con la orden.
    assert f"/portal/talleres-prueba?order={order_id}" in email.body
    assert email.html is not None and f"?order={order_id}" in email.html
    message = build_message(email, "AXTTON CORE <no-reply@axtton.example.com>")
    assert message["Reply-To"] == "taller@example.com"
    assert (await notices(engines))[f"quote_sent:{quote_id}"]["status"] == "sent"
    assert quote["status"] == "sent"


@pytest.mark.asyncio
async def test_the_email_goes_in_the_client_s_language(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    await set_client(engines, maria_with_email, language="en")
    order_id, _ = await sent_order(client, maria_with_email)
    workshop_id = await workshop_of(engines, order_id)
    [email] = (await deliver_due(workshop_id)).sent
    assert email.subject.startswith("Your quote from")
    assert "€121.00" in email.body and "VAT included" in email.body
    assert email.html is not None
    assert '<html lang="en">' in email.html
    assert "If the button does not work" in email.html
    # Sin nombre corto, la entrada por el id del taller.
    assert f"/portal/login/{workshop_id}?order={order_id}" in email.body


@pytest.mark.asyncio
async def test_without_email_the_notice_is_skipped(
    client: AsyncClient, shop: Shop, engines: Engines
) -> None:
    """RF-63: el envío se hace igual; el aviso queda omitido, con el motivo."""
    order_id, quote_id = await sent_order(client, shop)
    sent = await deliver_due(await workshop_of(engines, order_id))
    assert sent.sent == []
    notice = (await notices(engines))[f"quote_sent:{quote_id}"]
    assert (notice["status"], notice["failure_reason"]) == ("skipped", "no_email")


@pytest.mark.asyncio
async def test_an_archived_client_is_not_notified(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    order_id, quote_id = await sent_order(client, maria_with_email)
    await set_client(engines, maria_with_email, archived_at=None)
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE clients SET archived_at = clock_timestamp() WHERE id = :c"),
            {"c": maria_with_email.maria["id"]},
        )
    sent = await deliver_due(await workshop_of(engines, order_id))
    assert sent.sent == []
    notice = (await notices(engines))[f"quote_sent:{quote_id}"]
    assert (notice["status"], notice["failure_reason"]) == ("cancelled", "obsolete")


# --- La doble comprobación al enviar ------------------------------------------------


@pytest.mark.asyncio
async def test_a_correction_before_the_notice_leaves_only_the_new_version_s(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    """El taller corrige antes de que salga el aviso: el de la versión sustituida
    se cancela y solo sale el de la nueva."""
    order_id, first = await sent_order(client, maria_with_email)
    second = await draft_with_lines(client, maria_with_email, order_id)
    assert (await send(client, maria_with_email, order_id, second)).status_code == 204

    sent = await deliver_due(await workshop_of(engines, order_id))
    assert len(sent.sent) == 1 and "versión 2" in sent.sent[0].body
    found = await notices(engines)
    assert found[f"quote_sent:{first}"]["status"] == "cancelled"
    assert found[f"quote_sent:{second}"]["status"] == "sent"


@pytest.mark.asyncio
async def test_renewing_sends_a_notice_for_the_new_version(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    order_id, quote_id = await sent_order(client, maria_with_email)
    await expire_by_sql(quote_id)
    response = await renew(client, maria_with_email, order_id, quote_id)
    assert response.status_code == 201, response.text
    renewed = response.json()["id"]
    found = await notices(engines)
    assert found[f"quote_sent:{renewed}"]["status"] == "pending"


# --- La anulación -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelling_a_quote_the_client_received_tells_them_without_the_reason(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    order_id, quote_id = await sent_order(client, maria_with_email)
    workshop_id = await workshop_of(engines, order_id)
    assert len((await deliver_due(workshop_id)).sent) == 1

    reason = "Precio de la pieza equivocado, motivo interno"
    response = await cancel(client, maria_with_email, order_id, quote_id, reason)
    assert response.status_code == 204
    [email] = (await deliver_due(workshop_id)).sent
    assert "ha retirado la versión 1" in email.body
    # El motivo es interno, como en el PDF del cliente.
    assert "Precio de la pieza" not in email.body
    assert email.html is not None and "Precio de la pieza" not in email.html


@pytest.mark.asyncio
async def test_cancelling_before_the_client_got_it_tells_them_nothing(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    """Especificación §6: se avisa "si ya lo había recibido". Anulada antes de
    que saliera su aviso, no sale ninguno de los dos."""
    order_id, quote_id = await sent_order(client, maria_with_email)
    assert (
        await cancel(client, maria_with_email, order_id, quote_id)
    ).status_code == 204
    sent = await deliver_due(await workshop_of(engines, order_id))
    assert sent.sent == []
    found = await notices(engines)
    assert found[f"quote_sent:{quote_id}"]["status"] == "cancelled"
    assert found[f"quote_cancelled:{quote_id}"]["status"] == "cancelled"
