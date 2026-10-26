"""Diagnóstico, notas internas y trabajos por la API (RF-22 a RF-26, RNF-15).

Lo que garantiza la base de datos (append-only, anulación única) está en
test_worklog_db.py; los cruces con otras escrituras, en test_concurrency.py.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.api.deps import get_email_sender
from app.infra.email import InMemoryEmailSender
from app.main import app
from tests.test_clients import open_workshop
from tests.test_employees import add_mechanic, invite_and_accept
from tests.test_work_order_lifecycle import moved
from tests.test_work_orders import URL, Shop, codes, force_status, new_shop, open_order


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
async def order(client: AsyncClient, shop: Shop) -> dict[str, Any]:
    return await open_order(client, shop.headers, shop.car["id"])


@pytest_asyncio.fixture
async def juan(client: AsyncClient, shop: Shop) -> str:
    """La ficha de Juan, mecánico (sin acceso todavía)."""
    return await add_mechanic(client, shop.admin, "Juan")


async def worklog(client: AsyncClient, headers: dict[str, str], order_id: str) -> Any:
    response = await client.get(f"{URL}/{order_id}/worklog", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def diagnose(
    client: AsyncClient, headers: dict[str, str], order_id: str, base: int, text: str
) -> Any:
    return await client.post(
        f"{URL}/{order_id}/diagnosis",
        json={"base_version_no": base, "text": text},
        headers=headers,
    )


async def add_work(
    client: AsyncClient,
    headers: dict[str, str],
    order_id: str,
    employee_id: str,
    **fields: Any,
) -> Any:
    body = {
        "employee_id": employee_id,
        "description": "Cambio de pastillas delanteras",
        "worked_on": "2026-10-26",
        **fields,
    }
    return await client.post(
        f"{URL}/{order_id}/work-entries", json=body, headers=headers
    )


# --- Diagnóstico para el cliente (RF-22, RNF-15) -----------------------------


@pytest.mark.asyncio
async def test_each_save_is_a_new_version_and_the_last_one_is_current(
    client: AsyncClient, shop: Shop, order: dict[str, Any]
) -> None:
    first = await diagnose(client, shop.headers, order["id"], 0, "Pastillas gastadas.")
    second = await diagnose(
        client, shop.headers, order["id"], 1, "Pastillas y discos gastados."
    )
    assert (first.json(), second.json()) == ({"version_no": 1}, {"version_no": 2})

    log = await worklog(client, shop.headers, order["id"])
    current, older = log["diagnosis"]
    assert (current["version_no"], current["text"]) == (
        2,
        "Pastillas y discos gastados.",
    )
    assert (older["version_no"], older["text"]) == (1, "Pastillas gastadas.")
    assert current["employee_name"] == "Ana López"


@pytest.mark.asyncio
async def test_saving_from_an_old_version_is_a_409_and_keeps_the_other(
    client: AsyncClient, shop: Shop, order: dict[str, Any]
) -> None:
    """Dos personas abren el diagnóstico en la versión 1: la segunda en guardar
    no pisa a la primera (RNF-15)."""
    await diagnose(client, shop.headers, order["id"], 0, "Inicial")
    await diagnose(client, shop.headers, order["id"], 1, "De Ana")
    late = await diagnose(client, shop.headers, order["id"], 1, "De Juan")
    assert (late.status_code, late.json()) == (
        409,
        {"code": "modified_by_someone_else"},
    )
    log = await worklog(client, shop.headers, order["id"])
    assert [v["text"] for v in log["diagnosis"]] == ["De Ana", "Inicial"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", [{"base_version_no": 0, "text": "  "}, {"base_version_no": -1, "text": "x"}]
)
async def test_an_empty_diagnosis_or_a_negative_base_is_a_422(
    client: AsyncClient, shop: Shop, order: dict[str, Any], body: dict[str, Any]
) -> None:
    response = await client.post(
        f"{URL}/{order['id']}/diagnosis", json=body, headers=shop.headers
    )
    assert response.status_code == 422


# --- Notas internas (RF-22) --------------------------------------------------


@pytest.mark.asyncio
async def test_notes_are_a_thread_in_order(
    client: AsyncClient, shop: Shop, order: dict[str, Any]
) -> None:
    for body in ("Ruido solo en frío", "  Pedir discos  "):
        response = await client.post(
            f"{URL}/{order['id']}/notes", json={"body": body}, headers=shop.headers
        )
        assert response.status_code == 201
    notes = (await worklog(client, shop.headers, order["id"]))["notes"]
    assert [n["body"] for n in notes] == ["Ruido solo en frío", "Pedir discos"]
    assert notes[0]["seq"] < notes[1]["seq"]


@pytest.mark.asyncio
async def test_a_closed_order_still_takes_notes_but_nothing_else(
    client: AsyncClient, shop: Shop, order: dict[str, Any], juan: str
) -> None:
    """RF-26: una orden entregada o cancelada solo admite notas (y su cobro)."""
    await force_status(order["id"], "delivered")
    note = await client.post(
        f"{URL}/{order['id']}/notes",
        json={"body": "Llamó para dar las gracias"},
        headers=shop.headers,
    )
    assert note.status_code == 201
    for response in (
        await diagnose(client, shop.headers, order["id"], 0, "Tarde"),
        await add_work(client, shop.headers, order["id"], juan),
    ):
        assert (response.status_code, response.json()) == (
            409,
            {"code": "work_order_closed"},
        )


# --- Trabajos (RF-23, RF-25) -------------------------------------------------


@pytest.mark.asyncio
async def test_a_work_entry_records_who_did_it_even_if_another_writes_it(
    client: AsyncClient, shop: Shop, order: dict[str, Any], juan: str
) -> None:
    response = await add_work(client, shop.headers, order["id"], juan, hours="1.50")
    assert response.status_code == 201
    [entry] = (await worklog(client, shop.headers, order["id"]))["work_entries"]
    assert entry["employee"] == {"id": juan, "name": "Juan"}
    assert entry["recorded_by_name"] == "Ana López"
    assert (entry["hours"], entry["worked_on"], entry["voided_at"]) == (
        "1.50",
        "2026-10-26",
        None,
    )


@pytest.mark.asyncio
async def test_a_work_entry_is_activity_without_bumping_the_order_version(
    client: AsyncClient, shop: Shop, order: dict[str, Any], juan: str
) -> None:
    """RF-24: deja de estar "parada". Pero no sube la versión: quien tenga
    abierta la recepción no recibe un 409 por un trabajo que no la toca."""
    await add_work(client, shop.headers, order["id"], juan)
    after = (await client.get(f"{URL}/{order['id']}", headers=shop.headers)).json()
    assert after["last_activity_at"] > order["last_activity_at"]
    assert after["version"] == order["version"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields",
    [{"hours": "0"}, {"hours": "1000"}, {"hours": "1.234"}, {"description": " "}],
)
async def test_invalid_work_entries_are_a_422(
    client: AsyncClient,
    shop: Shop,
    order: dict[str, Any],
    juan: str,
    fields: dict[str, Any],
) -> None:
    assert (
        await add_work(client, shop.headers, order["id"], juan, **fields)
    ).status_code == 422


@pytest.mark.asyncio
async def test_workers_come_from_the_entries_that_count(
    client: AsyncClient, shop: Shop, order: dict[str, Any], juan: str
) -> None:
    """RF-25: los que han trabajado no se mantienen a mano: son los de los
    trabajos sin anular."""
    pepe = await add_mechanic(client, shop.admin, "Pepe")
    await add_work(client, shop.headers, order["id"], juan)
    wrong = (await add_work(client, shop.headers, order["id"], pepe)).json()["id"]
    assert (await worklog(client, shop.headers, order["id"]))["workers"] == [
        "Juan",
        "Pepe",
    ]

    void = await client.post(
        f"{URL}/{order['id']}/work-entries/{wrong}/void", headers=shop.headers
    )
    assert void.status_code == 204
    log = await worklog(client, shop.headers, order["id"])
    assert log["workers"] == ["Juan"]
    # Anulado, no borrado: sigue en la lista, marcado.
    assert [e["voided_at"] is not None for e in log["work_entries"]] == [False, True]
    again = await client.post(
        f"{URL}/{order['id']}/work-entries/{wrong}/void", headers=shop.headers
    )
    assert (again.status_code, again.json()) == (
        409,
        {"code": "work_entry_already_voided"},
    )


@pytest.mark.asyncio
async def test_an_inactive_or_foreign_card_cannot_have_done_the_work(
    client: AsyncClient, shop: Shop, order: dict[str, Any], juan: str
) -> None:
    await client.patch(
        f"/api/v1/workshop/employees/{juan}",
        json={"version": 1, "active": False},
        headers=shop.headers,
    )
    inactive = await add_work(client, shop.headers, order["id"], juan)
    assert (inactive.status_code, inactive.json()) == (
        404,
        {"code": "employee_not_found"},
    )

    b = await open_workshop(client, "Taller B")
    juan_b = await add_mechanic(client, b, "Juan de B")
    foreign = await add_work(client, shop.headers, order["id"], juan_b)
    assert (foreign.status_code, foreign.json()) == (
        404,
        {"code": "employee_not_found"},
    )


# --- El mecánico (especificación §3) -----------------------------------------


@pytest.mark.asyncio
async def test_a_mechanic_writes_diagnosis_notes_and_work_and_voids_only_his(
    client: AsyncClient,
    shop: Shop,
    order: dict[str, Any],
    juan: str,
    outbox: InMemoryEmailSender,
) -> None:
    mechanic = await invite_and_accept(client, shop.admin, outbox, juan)
    oid = order["id"]
    assert (await diagnose(client, mechanic, oid, 0, "Pastillas")).status_code == 201
    note = await client.post(
        f"{URL}/{oid}/notes", json={"body": "Ojo"}, headers=mechanic
    )
    assert note.status_code == 201
    his = (await add_work(client, mechanic, oid, juan)).json()["id"]
    hers = (await add_work(client, shop.headers, oid, juan)).json()["id"]

    log = await worklog(client, mechanic, oid)
    assert {e["id"]: e["can_void"] for e in log["work_entries"]} == {
        his: True,
        hers: False,
    }
    forbidden = await client.post(
        f"{URL}/{oid}/work-entries/{hers}/void", headers=mechanic
    )
    assert (forbidden.status_code, forbidden.json()) == (403, {"code": "not_allowed"})
    assert (
        await client.post(f"{URL}/{oid}/work-entries/{his}/void", headers=mechanic)
    ).status_code == 204
    # El administrador anula cualquiera.
    admin_view = await worklog(client, shop.headers, oid)
    assert {e["id"]: e["can_void"] for e in admin_view["work_entries"]} == {
        his: False,  # ya anulado
        hers: True,
    }


@pytest.mark.asyncio
async def test_mine_includes_the_orders_i_worked_on(
    client: AsyncClient, shop: Shop, juan: str, outbox: InMemoryEmailSender
) -> None:
    """RF-24: "mis órdenes" son de las que soy responsable o en las que he
    registrado trabajo (sin anular)."""
    mechanic = await invite_and_accept(client, shop.admin, outbox, juan)
    responsible = await open_order(
        client, shop.headers, shop.car["id"], responsible_employee_id=juan
    )
    worked = await open_order(client, shop.headers, shop.car["id"])
    voided = await open_order(client, shop.headers, shop.car["id"])
    await open_order(client, shop.headers, shop.car["id"])
    await add_work(client, shop.headers, worked["id"], juan)
    entry = (await add_work(client, shop.headers, voided["id"], juan)).json()["id"]
    await client.post(
        f"{URL}/{voided['id']}/work-entries/{entry}/void", headers=shop.headers
    )

    assert await codes(client, mechanic, mine=True) == [
        worked["code"],
        responsible["code"],
    ]


# --- Cancelar (§6) -----------------------------------------------------------


@pytest.mark.asyncio
async def test_an_order_with_work_cannot_be_cancelled_until_it_is_voided(
    client: AsyncClient, shop: Shop, order: dict[str, Any], juan: str
) -> None:
    """Cancelar es para órdenes abiertas por error: sin trabajos registrados."""
    entry = (await add_work(client, shop.headers, order["id"], juan)).json()["id"]
    current = (await client.get(f"{URL}/{order['id']}", headers=shop.headers)).json()
    refused = await client.post(
        f"{URL}/{order['id']}/status",
        json={"version": current["version"], "to_status": "cancelled", "note": "Error"},
        headers=shop.headers,
    )
    assert (refused.status_code, refused.json()) == (
        409,
        {"code": "work_order_has_work"},
    )

    await client.post(
        f"{URL}/{order['id']}/work-entries/{entry}/void", headers=shop.headers
    )
    cancelled = await moved(
        client, shop.headers, order["id"], "cancelled", note="Error"
    )
    assert cancelled["status"] == "cancelled"


# --- Aislamiento entre talleres ----------------------------------------------


@pytest.mark.asyncio
async def test_the_worklog_of_another_workshop_does_not_exist(
    client: AsyncClient, shop: Shop, order: dict[str, Any], juan: str
) -> None:
    entry = (await add_work(client, shop.headers, order["id"], juan)).json()["id"]
    b = (await open_workshop(client, "Taller B")).headers
    oid = order["id"]
    for response in (
        await client.get(f"{URL}/{oid}/worklog", headers=b),
        await diagnose(client, b, oid, 0, "x"),
        await client.post(f"{URL}/{oid}/notes", json={"body": "x"}, headers=b),
        await client.post(f"{URL}/{oid}/work-entries/{entry}/void", headers=b),
    ):
        assert (response.status_code, response.json()) == (
            404,
            {"code": "work_order_not_found"},
        )
    # Un trabajo de otra orden del mismo taller tampoco se anula por esta.
    other = await open_order(client, shop.headers, shop.car["id"])
    mismatch = await client.post(
        f"{URL}/{other['id']}/work-entries/{entry}/void", headers=shop.headers
    )
    assert (mismatch.status_code, mismatch.json()) == (
        404,
        {"code": "work_entry_not_found"},
    )


@pytest.mark.asyncio
async def test_everyone_sees_the_staff_directory_but_only_names(
    client: AsyncClient, shop: Shop, juan: str, outbox: InMemoryEmailSender
) -> None:
    """Para anotar el trabajo de un compañero, el mecánico necesita saber quién
    hay; pero no su rol, sus costes ni su acceso (eso sigue en /employees)."""
    mechanic = await invite_and_accept(client, shop.admin, outbox, juan)
    pepe = await add_mechanic(client, shop.admin, "Pepe")
    await client.patch(
        f"/api/v1/workshop/employees/{pepe}",
        json={"version": 1, "active": False},
        headers=shop.headers,
    )
    response = await client.get("/api/v1/workshop/staff", headers=mechanic)
    assert response.status_code == 200
    assert [m["name"] for m in response.json()] == ["Ana López", "Juan"]
    assert set(response.json()[0]) == {"id", "name"}
