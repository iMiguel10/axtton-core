"""El aviso de vehículo listo (F5 paso 6, RF-60).

Nace con el cambio que pone la orden lista, con el `seq` de ese cambio en su
`dedupe_key` (arquitectura §8): deshacerlo cancela el aviso pendiente y volver a
marcarla es otro motivo. El compositor comprueba al enviar que la orden sigue
lista por ese mismo cambio.
"""

from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.domain.notifications import ready_key, ready_seq
from tests.conftest import Engines
from tests.test_concurrency import dispose_global_engines  # noqa: F401 (autouse)
from tests.test_quote_notices import deliver_due, notices, set_client, workshop_of
from tests.test_work_order_lifecycle import moved, undo
from tests.test_work_orders import Shop, force_status, open_order, outbox, shop

__all__ = ["outbox", "shop"]


@pytest_asyncio.fixture
async def maria_with_email(engines: Engines, shop: Shop) -> Shop:
    await set_client(engines, shop, email="maria@example.com")
    return shop


async def last_seq(engines: Engines, order_id: str) -> int:
    async with engines.platform.connect() as conn:
        seq = await conn.scalar(
            text(
                "SELECT max(seq) FROM work_order_status_changes"
                " WHERE work_order_id = :o"
            ),
            {"o": order_id},
        )
    assert isinstance(seq, int)
    return seq


async def ready_order(client: AsyncClient, shop: Shop) -> dict[str, Any]:
    """Una orden reparada y lista, por la API (pasa por el cambio de estado)."""
    order = await open_order(client, shop.headers, shop.car["id"])
    await force_status(order["id"], "in_repair")
    result: dict[str, Any] = await moved(client, shop.headers, order["id"], "ready")
    return result


def test_the_ready_key_carries_the_status_change() -> None:
    from uuid import uuid4

    order_id = uuid4()
    assert ready_seq(ready_key(order_id, 42)) == 42
    with pytest.raises(ValueError):
        ready_seq(f"quote_sent:{order_id}")


@pytest.mark.asyncio
async def test_marking_an_order_ready_creates_its_notice(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    order = await ready_order(client, maria_with_email)
    seq = await last_seq(engines, order["id"])
    notice = (await notices(engines))[f"ready:{order['id']}:{seq}"]
    assert (notice["kind"], notice["status"]) == ("vehicle_ready", "pending")
    assert str(notice["client_id"]) == maria_with_email.maria["id"]
    assert str(notice["work_order_id"]) == order["id"]


@pytest.mark.asyncio
async def test_the_ready_email_says_where_to_pick_it_up(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    order = await ready_order(client, maria_with_email)
    workshop_id = await workshop_of(engines, order["id"])
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "UPDATE workshops SET address = 'Calle Mayor 1, Madrid',"
                " phone = '910000000' WHERE id = :w"
            ),
            {"w": workshop_id},
        )
    [email] = (await deliver_due(workshop_id)).sent
    assert email.to == "maria@example.com"
    assert "está listo para recoger" in email.subject
    assert "ha terminado con tu vehículo" in email.body
    assert "Dirección: Calle Mayor 1, Madrid." in email.body
    assert "Teléfono: 910000000." in email.body
    assert f"?order={order['id']}" in email.body


@pytest.mark.asyncio
async def test_ready_unrepaired_says_so(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    """ "Lista sin reparar" (especificación §6): el cliente lo sabe por el correo,
    como en el portal."""
    order = await open_order(
        client, maria_with_email.headers, maria_with_email.car["id"]
    )
    await moved(client, maria_with_email.headers, order["id"], "diagnosing")
    await moved(
        client, maria_with_email.headers, order["id"], "ready", note="Nada que reparar"
    )
    [email] = (await deliver_due(await workshop_of(engines, order["id"]))).sent
    assert email.subject.endswith("sin reparar")
    assert "no ha reparado tu vehículo" in email.body


@pytest.mark.asyncio
async def test_undoing_ready_cancels_the_pending_notice(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    order = await ready_order(client, maria_with_email)
    seq = await last_seq(engines, order["id"])
    await undo(client, maria_with_email.headers, order["id"])
    notice = (await notices(engines))[ready_key(order["id"], seq)]
    assert (notice["status"], notice["failure_reason"]) == ("cancelled", "obsolete")
    sent = await deliver_due(await workshop_of(engines, order["id"]))
    assert sent.sent == []


@pytest.mark.asyncio
async def test_marking_it_ready_again_is_another_notice(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    """Deshacer y volver a marcarla lista es otro cambio: otro aviso, que sale."""
    order = await ready_order(client, maria_with_email)
    first = await last_seq(engines, order["id"])
    await undo(client, maria_with_email.headers, order["id"])
    await moved(client, maria_with_email.headers, order["id"], "ready")
    second = await last_seq(engines, order["id"])
    assert second != first

    sent = await deliver_due(await workshop_of(engines, order["id"]))
    assert len(sent.sent) == 1
    found = await notices(engines)
    assert found[ready_key(order["id"], first)]["status"] == "cancelled"
    assert found[ready_key(order["id"], second)]["status"] == "sent"


@pytest.mark.asyncio
async def test_a_notice_whose_order_moved_on_is_not_sent(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    """La doble comprobación al enviar: entregada antes de que saliera el aviso,
    ya no tiene sentido avisar de que está lista."""
    order = await ready_order(client, maria_with_email)
    seq = await last_seq(engines, order["id"])
    await moved(client, maria_with_email.headers, order["id"], "delivered")
    sent = await deliver_due(await workshop_of(engines, order["id"]))
    assert sent.sent == []
    notice = (await notices(engines))[ready_key(order["id"], seq)]
    assert (notice["status"], notice["failure_reason"]) == ("cancelled", "obsolete")


@pytest.mark.asyncio
async def test_undo_does_not_touch_a_notice_that_already_went_out(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    """Uno ya enviado no se puede deshacer: se queda `sent`."""
    order = await ready_order(client, maria_with_email)
    seq = await last_seq(engines, order["id"])
    assert len((await deliver_due(await workshop_of(engines, order["id"]))).sent) == 1
    await undo(client, maria_with_email.headers, order["id"])
    assert (await notices(engines))[ready_key(order["id"], seq)]["status"] == "sent"


@pytest.mark.asyncio
async def test_a_notice_in_flight_for_an_undone_change_is_not_sent(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    """El despachador ya había reclamado el aviso del primer "lista" cuando el
    taller deshizo y volvió a marcarla: deshacer no lo puede cancelar (se está
    enviando), así que lo para el compositor, porque la orden ya no está lista
    por ese cambio. Sale un solo correo, el del segundo."""
    from uuid import UUID

    from app.infra.email import InMemoryEmailSender
    from app.infra.queue import InMemoryJobQueue
    from app.services import notifications as notification_service
    from app.services.notice_composers import COMPOSERS

    order = await ready_order(client, maria_with_email)
    first = await last_seq(engines, order["id"])
    workshop_id = await workshop_of(engines, order["id"])
    queue = InMemoryJobQueue()
    assert (
        await notification_service.dispatch(workshop_id, queue, email_enabled=True) == 1
    )
    [in_flight] = queue.jobs

    await undo(client, maria_with_email.headers, order["id"])
    assert (await notices(engines))[ready_key(order["id"], first)][
        "status"
    ] == "claimed"
    await moved(client, maria_with_email.headers, order["id"], "ready")

    outbox = InMemoryEmailSender()
    late = await notification_service.deliver(
        workshop_id,
        UUID(str(in_flight.kwargs["notification_id"])),
        int(str(in_flight.kwargs["attempt"])),
        outbox,
        COMPOSERS,
    )
    assert late == "cancelled" and outbox.sent == []
    assert len((await deliver_due(workshop_id)).sent) == 1
