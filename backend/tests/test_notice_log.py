"""Lo que ve el taller de los avisos de una orden (F5 paso 7, RF-63, RF-69).

`GET /workshop/orders/{id}/notifications` da los avisos de esa orden, el más
reciente primero, con su estado y, si no salió, el motivo como código. La ficha
dice si el cliente tiene email, para que la interfaz avise antes de actuar.
"""

from typing import Any

import pytest
from httpx import AsyncClient

from app.infra.email import InMemoryEmailSender
from app.services import notifications as notification_service
from tests.conftest import Engines
from tests.test_clients import open_workshop
from tests.test_concurrency import dispose_global_engines  # noqa: F401 (autouse)
from tests.test_employees import add_mechanic, invite_and_accept
from tests.test_quote_decision import sent_order
from tests.test_quote_notices import deliver_due, set_client, workshop_of
from tests.test_ready_notice import ready_order
from tests.test_work_orders import URL, Shop, open_order, outbox, shop

__all__ = ["outbox", "shop"]

# Lo que la ruta enseña de cada aviso, y nada más: ni el email ni el texto.
FIELDS = {
    "id",
    "kind",
    "quote_version_no",
    "status",
    "failure_reason",
    "smtp_code",
    "attempts",
    "created_at",
    "sent_at",
    "next_attempt_at",
}


async def notices_of(
    client: AsyncClient, headers: dict[str, str], order_id: str
) -> list[dict[str, Any]]:
    response = await client.get(f"{URL}/{order_id}/notifications", headers=headers)
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()
    return found


@pytest.mark.asyncio
async def test_an_order_without_notices_has_an_empty_list(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    assert await notices_of(client, shop.headers, order["id"]) == []


@pytest.mark.asyncio
async def test_the_workshop_sees_what_went_out_and_when(
    client: AsyncClient, shop: Shop, engines: Engines
) -> None:
    await set_client(engines, shop, email="maria@example.com")
    order = await ready_order(client, shop)
    [pending] = await notices_of(client, shop.headers, order["id"])
    assert set(pending) == FIELDS
    assert (pending["kind"], pending["status"], pending["sent_at"]) == (
        "vehicle_ready",
        "pending",
        None,
    )

    assert len((await deliver_due(await workshop_of(engines, order["id"]))).sent) == 1
    [sent] = await notices_of(client, shop.headers, order["id"])
    assert (sent["status"], sent["attempts"], sent["failure_reason"]) == (
        "sent",
        1,
        None,
    )
    assert sent["sent_at"] is not None


@pytest.mark.asyncio
async def test_a_client_without_email_is_skipped_with_its_reason(
    client: AsyncClient, shop: Shop, engines: Engines
) -> None:
    """RF-63: la orden se marca lista igual y el taller ve por qué no se avisó."""
    order = await ready_order(client, shop)
    await deliver_due(await workshop_of(engines, order["id"]))
    [skipped] = await notices_of(client, shop.headers, order["id"])
    assert (skipped["status"], skipped["failure_reason"]) == ("skipped", "no_email")


@pytest.mark.asyncio
async def test_without_smtp_the_reason_is_that_email_is_disabled(
    client: AsyncClient, shop: Shop, engines: Engines
) -> None:
    """La demo no tiene correo: sus avisos dicen eso, no que fallaron."""
    from app.infra.queue import InMemoryJobQueue

    await set_client(engines, shop, email="maria@example.com")
    order = await ready_order(client, shop)
    workshop_id = await workshop_of(engines, order["id"])
    await notification_service.dispatch(
        workshop_id, InMemoryJobQueue(), email_enabled=False
    )
    [skipped] = await notices_of(client, shop.headers, order["id"])
    assert (skipped["status"], skipped["failure_reason"]) == (
        "skipped",
        "email_disabled",
    )


@pytest.mark.asyncio
async def test_quote_notices_say_which_version_and_come_newest_first(
    client: AsyncClient, shop: Shop, engines: Engines
) -> None:
    await set_client(engines, shop, email="maria@example.com")
    order_id, quote_id = await sent_order(client, shop)
    from tests.test_quote_send import cancel

    assert len((await deliver_due(await workshop_of(engines, order_id))).sent) == 1
    assert (await cancel(client, shop, order_id, quote_id)).status_code == 204
    found = await notices_of(client, shop.headers, order_id)
    assert [(n["kind"], n["status"], n["quote_version_no"]) for n in found] == [
        ("quote_cancelled", "pending", 1),
        ("quote_sent", "sent", 1),
    ]

    # Los de otra orden no salen en esta.
    order = await open_order(client, shop.headers, shop.car["id"])
    assert await notices_of(client, shop.headers, order["id"]) == []


@pytest.mark.asyncio
async def test_a_failed_attempt_shows_its_code_and_next_retry(
    client: AsyncClient, shop: Shop, engines: Engines
) -> None:
    from typing import cast
    from uuid import UUID

    from app.infra.email import EmailNotSentError
    from app.infra.queue import InMemoryJobQueue
    from app.services.notice_composers import COMPOSERS

    class Refusing(InMemoryEmailSender):
        async def send(self, email: Any) -> None:
            raise EmailNotSentError("mailbox full", smtp_code=452)

    await set_client(engines, shop, email="maria@example.com")
    order = await ready_order(client, shop)
    workshop_id = await workshop_of(engines, order["id"])
    queue = InMemoryJobQueue()
    await notification_service.dispatch(workshop_id, queue, email_enabled=True)
    [job] = queue.jobs
    await notification_service.deliver(
        workshop_id,
        UUID(cast(str, job.kwargs["notification_id"])),
        cast(int, job.kwargs["attempt"]),
        Refusing(),
        COMPOSERS,
    )
    [failed] = await notices_of(client, shop.headers, order["id"])
    assert (
        failed["status"],
        failed["failure_reason"],
        failed["smtp_code"],
        failed["attempts"],
    ) == ("failed", "not_sent", 452, 1)
    assert failed["next_attempt_at"] is not None


@pytest.mark.asyncio
async def test_the_mechanic_sees_them_too(
    client: AsyncClient, shop: Shop, outbox: InMemoryEmailSender
) -> None:
    """Ve las órdenes (especificación §3), y aquí no hay datos del cliente."""
    order = await ready_order(client, shop)
    juan = await add_mechanic(client, shop.admin, "Juan")
    mechanic = await invite_and_accept(client, shop.admin, outbox, juan)
    [notice] = await notices_of(client, mechanic, order["id"])
    assert notice["kind"] == "vehicle_ready"


@pytest.mark.asyncio
async def test_the_notices_of_another_workshop_s_order_do_not_exist(
    client: AsyncClient, shop: Shop
) -> None:
    order = await ready_order(client, shop)
    b = (await open_workshop(client, "Taller B")).headers
    response = await client.get(f"{URL}/{order['id']}/notifications", headers=b)
    assert (response.status_code, response.json()) == (
        404,
        {"code": "work_order_not_found"},
    )


@pytest.mark.asyncio
async def test_the_order_says_whether_the_client_has_an_email(
    client: AsyncClient, shop: Shop, engines: Engines
) -> None:
    """RF-63: la interfaz avisa antes de actuar, sin recibir el email."""
    order = await open_order(client, shop.headers, shop.car["id"])

    async def client_of_order() -> dict[str, Any]:
        detail = await client.get(f"{URL}/{order['id']}", headers=shop.headers)
        found: dict[str, Any] = detail.json()["client"]
        return found

    assert (await client_of_order())["has_email"] is False
    await set_client(engines, shop, email="maria@example.com")
    found = await client_of_order()
    assert found["has_email"] is True
    assert "email" not in found
    listed = await client.get(URL, headers=shop.headers)
    assert [row["client"]["has_email"] for row in listed.json()] == [True]
