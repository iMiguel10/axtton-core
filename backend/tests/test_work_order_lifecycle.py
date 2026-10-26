"""El ciclo de vida de una orden por la API (especificación §6, RF-26, RF-27).

Las reglas puras están en test_domain_work_orders.py; aquí, que la API las
aplica, con los permisos reales de cada rol, el historial por `seq` y la
auditoría. Los cambios simultáneos, en test_concurrency.py.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.api.deps import get_email_sender
from app.infra.email import InMemoryEmailSender
from app.main import app
from tests.conftest import Engines
from tests.test_clients import open_workshop
from tests.test_employees import add_mechanic, invite_and_accept
from tests.test_work_orders import URL, Shop, get, new_shop, open_order


@pytest_asyncio.fixture
async def outbox() -> AsyncIterator[InMemoryEmailSender]:
    sender = InMemoryEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    yield sender
    app.dependency_overrides.pop(get_email_sender, None)


@pytest_asyncio.fixture
async def shop(client: AsyncClient) -> Shop:
    return await new_shop(client)


@pytest_asyncio.fixture
async def mechanic(
    client: AsyncClient, shop: Shop, outbox: InMemoryEmailSender
) -> dict[str, str]:
    """Juan, mecánico con acceso al taller."""
    juan = await add_mechanic(client, shop.admin, "Juan")
    return await invite_and_accept(client, shop.admin, outbox, juan)


async def move(
    client: AsyncClient,
    headers: dict[str, str],
    order_id: str,
    to: str,
    note: str | None = None,
) -> Any:
    """Pide el cambio con la versión que hay ahora y devuelve la respuesta."""
    current = await get(client, headers, order_id)
    return await client.post(
        f"{URL}/{order_id}/status",
        json={"version": current["version"], "to_status": to, "note": note},
        headers=headers,
    )


async def moved(
    client: AsyncClient,
    headers: dict[str, str],
    order_id: str,
    to: str,
    note: str | None = None,
) -> Any:
    response = await move(client, headers, order_id, to, note)
    assert response.status_code == 204, response.text
    return await get(client, headers, order_id)


async def undo(client: AsyncClient, headers: dict[str, str], order_id: str) -> Any:
    current = await get(client, headers, order_id)
    return await client.post(
        f"{URL}/{order_id}/undo", json={"version": current["version"]}, headers=headers
    )


async def mark_no_quote(
    client: AsyncClient, headers: dict[str, str], order_id: str, reason: str | None
) -> Any:
    current = await get(client, headers, order_id)
    return await client.post(
        f"{URL}/{order_id}/no-quote",
        json={"version": current["version"], "reason": reason},
        headers=headers,
    )


def statuses(order: dict[str, Any]) -> list[tuple[str | None, str, str]]:
    return [(c["from_status"], c["to_status"], c["cause"]) for c in order["history"]]


# --- El recorrido completo ---------------------------------------------------


@pytest.mark.asyncio
async def test_a_warranty_repair_goes_from_received_to_delivered(
    client: AsyncClient, shop: Shop, mechanic: dict[str, str]
) -> None:
    """Sin presupuesto (garantía): el administrador la recibe y la marca, el
    mecánico la repara y la deja lista, y el administrador la entrega."""
    admin = shop.headers
    order = await open_order(client, admin, shop.car["id"])
    oid = order["id"]

    await moved(client, admin, oid, "diagnosing")
    assert (await mark_no_quote(client, admin, oid, "warranty")).status_code == 204
    await moved(client, mechanic, oid, "in_repair")
    await moved(client, mechanic, oid, "waiting_parts")
    await moved(client, mechanic, oid, "in_repair")
    await moved(client, mechanic, oid, "ready")
    delivered = await moved(client, admin, oid, "delivered")

    assert delivered["status"] == "delivered"
    assert delivered["delivered_at"] is not None
    assert delivered["no_quote_reason"] == "warranty"
    # El historial, por seq: del primero al último, y el último es el estado.
    assert statuses(delivered) == [
        (None, "received", "opened"),
        ("received", "diagnosing", "manual"),
        ("diagnosing", "in_repair", "manual"),
        ("in_repair", "waiting_parts", "manual"),
        ("waiting_parts", "in_repair", "manual"),
        ("in_repair", "ready", "manual"),
        ("ready", "delivered", "manual"),
    ]
    seqs = [c["seq"] for c in delivered["history"]]
    assert seqs == sorted(seqs)
    who = [c["employee_name"] for c in delivered["history"]]
    assert who == [
        "Ana López",
        "Ana López",
        "Juan",
        "Juan",
        "Juan",
        "Juan",
        "Ana López",
    ]
    # Cada cambio sube la versión: quien tuviera la ficha abierta no la pisa.
    assert delivered["version"] > order["version"]
    # Cerrada: ya no se mueve (RF-26).
    assert delivered["allowed_transitions"] == []
    again = await move(client, admin, oid, "ready")
    assert (again.status_code, again.json()) == (409, {"code": "invalid_transition"})


@pytest.mark.asyncio
async def test_a_status_change_is_activity(client: AsyncClient, shop: Shop) -> None:
    """RF-24: una orden con un cambio reciente deja de estar "parada"."""
    order = await open_order(client, shop.headers, shop.car["id"])
    after = await moved(client, shop.headers, order["id"], "diagnosing")
    assert after["last_activity_at"] > order["last_activity_at"]


# --- Quién puede (especificación §3) ----------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setup", "to"),
    [
        ([], "diagnosing"),
        (["diagnosing"], "ready"),
        ([], "cancelled"),
    ],
)
async def test_a_mechanic_cannot_make_the_admins_changes(
    client: AsyncClient,
    shop: Shop,
    mechanic: dict[str, str],
    setup: list[str],
    to: str,
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    for status in setup:
        await moved(client, shop.headers, order["id"], status)
    response = await move(client, mechanic, order["id"], to, note="porque sí")
    assert (response.status_code, response.json()) == (403, {"code": "not_allowed"})


@pytest.mark.asyncio
async def test_a_mechanic_cannot_deliver_undo_or_mark_no_quote(
    client: AsyncClient, shop: Shop, mechanic: dict[str, str]
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    await moved(client, shop.headers, order["id"], "diagnosing")
    for response in (
        await undo(client, mechanic, order["id"]),
        await mark_no_quote(client, mechanic, order["id"], "warranty"),
    ):
        assert (response.status_code, response.json()) == (403, {"code": "not_allowed"})

    await mark_no_quote(client, shop.headers, order["id"], "warranty")
    for status in ("in_repair", "ready"):
        await moved(client, mechanic, order["id"], status)
    delivery = await move(client, mechanic, order["id"], "delivered")
    assert (delivery.status_code, delivery.json()) == (403, {"code": "not_allowed"})


@pytest.mark.asyncio
async def test_the_detail_tells_each_role_what_it_can_do(
    client: AsyncClient, shop: Shop, mechanic: dict[str, str]
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])

    def targets(detail: dict[str, Any]) -> set[str]:
        return {t["to_status"] for t in detail["allowed_transitions"]}

    as_admin = await get(client, shop.headers, order["id"])
    as_mechanic = await get(client, mechanic, order["id"])
    assert targets(as_admin) == {"diagnosing", "cancelled"}
    assert (as_admin["can_undo"], as_admin["can_mark_no_quote"]) == (False, True)
    assert targets(as_mechanic) == set()
    assert (as_mechanic["can_undo"], as_mechanic["can_mark_no_quote"]) == (False, False)

    await moved(client, shop.headers, order["id"], "diagnosing")
    as_admin = await get(client, shop.headers, order["id"])
    assert targets(as_admin) == {"ready", "cancelled"}
    assert next(
        t for t in as_admin["allowed_transitions"] if t["to_status"] == "ready"
    ) == {
        "to_status": "ready",
        "needs_note": True,
        "unrepaired": True,
    }
    assert as_admin["can_undo"] is True


# --- Reglas (§6, RF-27) ------------------------------------------------------


@pytest.mark.asyncio
async def test_an_impossible_change_is_a_409_and_changes_nothing(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    for to in ("ready", "delivered", "pending_approval", "approved", "received"):
        response = await move(client, shop.headers, order["id"], to)
        assert (response.status_code, response.json()) == (
            409,
            {"code": "invalid_transition"},
        ), to
    after = await get(client, shop.headers, order["id"])
    assert (after["status"], len(after["history"]), after["version"]) == (
        "received",
        1,
        order["version"],
    )


@pytest.mark.asyncio
async def test_repairing_without_a_quote_needs_the_no_quote_mark(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    response = await move(client, shop.headers, order["id"], "in_repair")
    assert (response.status_code, response.json()) == (
        409,
        {"code": "no_quote_reason_required"},
    )
    await mark_no_quote(client, shop.headers, order["id"], "fixed_price")
    assert (await moved(client, shop.headers, order["id"], "in_repair"))[
        "status"
    ] == "in_repair"


@pytest.mark.asyncio
async def test_the_no_quote_mark_rules(client: AsyncClient, shop: Shop) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    oid = order["id"]
    # La renuncia del cliente exige la hoja de recepción firmada (RF-27, F6).
    waiver = await mark_no_quote(client, shop.headers, oid, "waiver")
    assert (waiver.status_code, waiver.json()) == (
        409,
        {"code": "waiver_requires_signed_reception"},
    )
    assert (
        await mark_no_quote(client, shop.headers, oid, "warranty")
    ).status_code == 204
    # Se puede quitar mientras no ha empezado la reparación...
    assert (await mark_no_quote(client, shop.headers, oid, None)).status_code == 204
    await mark_no_quote(client, shop.headers, oid, "warranty")
    await moved(client, shop.headers, oid, "in_repair")
    # ...pero no después.
    late = await mark_no_quote(client, shop.headers, oid, None)
    assert (late.status_code, late.json()) == (409, {"code": "no_quote_not_now"})

    audit = await client.get("/api/v1/workshop/audit", headers=shop.headers)
    marks = [e for e in audit.json()["entries"] if e["action"] == "no_quote_marked"]
    assert [e["details"] for e in marks] == [
        {"no_quote_reason": [None, "warranty"]},
        {"no_quote_reason": ["warranty", None]},
        {"no_quote_reason": [None, "warranty"]},
    ][::-1]
    assert marks[0]["target_name"] == order["code"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setup", "to"), [([], "cancelled"), (["diagnosing"], "ready")]
)
async def test_cancelling_and_unrepaired_need_a_note(
    client: AsyncClient, shop: Shop, setup: list[str], to: str
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    for status in setup:
        await moved(client, shop.headers, order["id"], status)
    for note in (None, "  "):
        response = await move(client, shop.headers, order["id"], to, note=note)
        assert (response.status_code, response.json()) == (
            422,
            {"code": "note_required"},
        )
    done = await moved(
        client, shop.headers, order["id"], to, note="  Abierta por error  "
    )
    assert done["history"][-1]["note"] == "Abierta por error"


@pytest.mark.asyncio
async def test_unrepaired_is_ready_and_leaves_by_delivered(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    await moved(client, shop.headers, order["id"], "diagnosing")
    ready = await moved(
        client, shop.headers, order["id"], "ready", note="No encontramos la avería"
    )
    assert (ready["status"], ready["unrepaired"]) == ("ready", True)
    delivered = await moved(client, shop.headers, order["id"], "delivered")
    assert (delivered["status"], delivered["unrepaired"]) == ("delivered", True)


@pytest.mark.asyncio
async def test_a_change_with_an_old_version_is_a_409(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    await moved(client, shop.headers, order["id"], "diagnosing")
    stale = await client.post(
        f"{URL}/{order['id']}/status",
        json={"version": order["version"], "to_status": "cancelled", "note": "x"},
        headers=shop.headers,
    )
    assert (stale.status_code, stale.json()) == (
        409,
        {"code": "modified_by_someone_else"},
    )
    assert (await get(client, shop.headers, order["id"]))["status"] == "diagnosing"


# --- Deshacer (§6, RNF-16) ---------------------------------------------------


@pytest.mark.asyncio
async def test_undo_adds_a_compensating_change_and_never_deletes(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    diagnosing = await moved(client, shop.headers, order["id"], "diagnosing")
    assert (await undo(client, shop.headers, order["id"])).status_code == 204

    after = await get(client, shop.headers, order["id"])
    assert after["status"] == "received"
    assert statuses(after) == [
        (None, "received", "opened"),
        ("received", "diagnosing", "manual"),
        ("diagnosing", "received", "undo"),
    ]
    assert after["history"][-1]["undoes_seq"] == diagnosing["history"][-1]["seq"]
    # No hay "rehacer": lo último es un deshacer, que no se deshace.
    assert after["can_undo"] is False
    again = await undo(client, shop.headers, order["id"])
    assert (again.status_code, again.json()) == (409, {"code": "cannot_undo_automatic"})

    audit = await client.get("/api/v1/workshop/audit", headers=shop.headers)
    [entry] = [
        e for e in audit.json()["entries"] if e["action"] == "status_change_undone"
    ]
    assert entry["details"] == {"work_order_status": ["diagnosing", "received"]}
    assert (entry["target_name"], entry["actor"]) == (order["code"], "Ana López")


@pytest.mark.asyncio
async def test_the_opening_cannot_be_undone(client: AsyncClient, shop: Shop) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    response = await undo(client, shop.headers, order["id"])
    assert (response.status_code, response.json()) == (
        409,
        {"code": "cannot_undo_automatic"},
    )


@pytest.mark.asyncio
async def test_undoing_unrepaired_also_undoes_the_unrepaired_mark(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    await moved(client, shop.headers, order["id"], "diagnosing")
    await moved(client, shop.headers, order["id"], "ready", note="Nada que reparar")
    await undo(client, shop.headers, order["id"])
    after = await get(client, shop.headers, order["id"])
    assert (after["status"], after["unrepaired"]) == ("diagnosing", False)


@pytest.mark.asyncio
@pytest.mark.parametrize("to", ["delivered", "cancelled"])
async def test_a_change_that_closed_the_order_cannot_be_undone(
    client: AsyncClient, shop: Shop, to: str
) -> None:
    """Una orden entregada no se reabre nunca (§6), tampoco deshaciendo."""
    order = await open_order(client, shop.headers, shop.car["id"])
    if to == "delivered":
        await moved(client, shop.headers, order["id"], "diagnosing")
        await moved(client, shop.headers, order["id"], "ready", note="Nada")
    await moved(client, shop.headers, order["id"], to, note="Por error")
    response = await undo(client, shop.headers, order["id"])
    assert (response.status_code, response.json()) == (
        409,
        {"code": "cannot_undo_closing"},
    )


@pytest.mark.asyncio
async def test_a_change_that_notified_the_client_cannot_be_undone(
    client: AsyncClient, shop: Shop, engines: Engines
) -> None:
    """Deshacer "lista" no puede desenviar el email (§6). `notified` lo pondrá
    la bandeja de avisos (F5); aquí se marca a mano."""
    order = await open_order(client, shop.headers, shop.car["id"])
    await moved(client, shop.headers, order["id"], "diagnosing")
    # Con el rol de plataforma: axtton_app no puede actualizar el historial.
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "UPDATE work_order_status_changes SET notified = true"
                " WHERE work_order_id = :o AND to_status = 'diagnosing'"
            ),
            {"o": order["id"]},
        )
    response = await undo(client, shop.headers, order["id"])
    assert (response.status_code, response.json()) == (
        409,
        {"code": "cannot_undo_notified"},
    )
    assert (await get(client, shop.headers, order["id"]))["can_undo"] is False


# --- Aislamiento entre talleres ----------------------------------------------


@pytest.mark.asyncio
async def test_an_order_of_another_workshop_cannot_be_moved(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    b = (await open_workshop(client, "Taller B")).headers
    version = {"version": order["version"]}
    for response in (
        await client.post(
            f"{URL}/{order['id']}/status",
            json={**version, "to_status": "diagnosing"},
            headers=b,
        ),
        await client.post(f"{URL}/{order['id']}/undo", json=version, headers=b),
        await client.post(
            f"{URL}/{order['id']}/no-quote",
            json={**version, "reason": "warranty"},
            headers=b,
        ),
    ):
        assert (response.status_code, response.json()) == (
            404,
            {"code": "work_order_not_found"},
        )
    assert (await get(client, shop.headers, order["id"]))["status"] == "received"
