"""El libro de movimientos de stock por la API (F7 paso 2, RF-91 a RF-96).

Las carreras van en test_concurrency.py, con transacciones reales; los
triggers y los permisos de la base de datos, en test_stock_db.py.
"""

import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql

from app.api.deps import get_email_sender
from app.infra.email import InMemoryEmailSender
from app.main import app
from app.scripts.reset_data import truncate_all
from tests.conftest import Engines
from tests.test_clients import open_workshop
from tests.test_employees import AdminSession, add_mechanic, invite_and_accept
from tests.test_limits import refused
from tests.test_parts import URL as PARTS
from tests.test_parts import create, listed


@pytest_asyncio.fixture
async def admin(client: AsyncClient) -> AdminSession:
    await truncate_all()
    return await open_workshop(client, "Talleres Pérez")


@pytest_asyncio.fixture
async def mechanic(
    client: AsyncClient, admin: AdminSession
) -> AsyncIterator[dict[str, str]]:
    sender = InMemoryEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    try:
        yield await invite_and_accept(
            client, admin, sender, await add_mechanic(client, admin)
        )
    finally:
        app.dependency_overrides.pop(get_email_sender, None)


MOVEMENTS = "/api/v1/workshop/stock-movements"


async def move(
    client: AsyncClient,
    headers: dict[str, str],
    part_id: str,
    what: str,
    body: dict[str, Any],
    status: int = 201,
) -> dict[str, Any]:
    response = await client.post(
        f"{PARTS}/{part_id}/stock/{what}", json=body, headers=headers
    )
    assert response.status_code == status, response.text
    result: dict[str, Any] = response.json()
    return result


async def entry(
    client: AsyncClient, headers: dict[str, str], part_id: str, quantity: str
) -> str:
    created = await move(
        client,
        headers,
        part_id,
        "entries",
        {"quantity": quantity, "unit_cost_cents": 6000, "note": "Albarán 12"},
    )
    movement_id: str = created["id"]
    return movement_id


async def part_of(
    client: AsyncClient, headers: dict[str, str], part_id: str
) -> dict[str, Any]:
    response = await client.get(f"{PARTS}/{part_id}", headers=headers)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


async def history(
    client: AsyncClient, headers: dict[str, str], part_id: str, **params: Any
) -> dict[str, Any]:
    response = await client.get(
        f"{PARTS}/{part_id}/movements", params=params, headers=headers
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


# --- Entradas, ajustes y el stock como suma (invariante 9) -------------------


@pytest.mark.asyncio
async def test_the_stock_is_the_sum_of_entries_and_adjustments(
    client: AsyncClient, admin: AdminSession
) -> None:
    part = await create(client, admin.headers)
    assert part["stock"] == "0"
    await entry(client, admin.headers, part["id"], "5")
    await entry(client, admin.headers, part["id"], "1.5")
    await move(
        client,
        admin.headers,
        part["id"],
        "adjustments",
        {"quantity": "-2", "note": "Una llegó rota"},
    )
    assert (await part_of(client, admin.headers, part["id"]))["stock"] == "4.500"
    (listed_part,) = (await listed(client, admin.headers))["parts"]
    assert listed_part["stock"] == "4.500"


@pytest.mark.asyncio
async def test_the_history_shows_each_movement_newest_first_with_its_author(
    client: AsyncClient, admin: AdminSession
) -> None:
    part = await create(client, admin.headers)
    await entry(client, admin.headers, part["id"], "5")
    await move(
        client,
        admin.headers,
        part["id"],
        "adjustments",
        {"quantity": "-1", "note": "Rotura"},
    )
    adjustment, first = (await history(client, admin.headers, part["id"]))["movements"]
    assert (first["kind"], first["quantity"], first["unit_cost_cents"]) == (
        "in",
        "5.000",
        6000,
    )
    assert first["note"] == "Albarán 12"
    assert (adjustment["kind"], adjustment["quantity"], adjustment["note"]) == (
        "adjustment",
        "-1.000",
        "Rotura",
    )
    assert adjustment["seq"] > first["seq"]
    assert adjustment["employee_name"] == first["employee_name"] != ""


@pytest.mark.asyncio
async def test_the_history_is_paged_by_seq(
    client: AsyncClient, admin: AdminSession
) -> None:
    part = await create(client, admin.headers)
    for _ in range(3):
        await entry(client, admin.headers, part["id"], "1")
    page = await history(client, admin.headers, part["id"], limit=2)
    assert len(page["movements"]) == 2
    rest = await history(
        client, admin.headers, part["id"], limit=2, before=page["next_before"]
    )
    assert len(rest["movements"]) == 1
    assert rest["next_before"] is None
    seqs = [m["seq"] for m in page["movements"] + rest["movements"]]
    assert seqs == sorted(seqs, reverse=True)


# --- Recuento (RF-92) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_count_adjusts_the_stock_to_what_was_counted(
    client: AsyncClient, admin: AdminSession
) -> None:
    part = await create(client, admin.headers)
    await entry(client, admin.headers, part["id"], "5")
    counted = await move(
        client,
        admin.headers,
        part["id"],
        "count",
        {"counted": "3", "expected": "5"},
        status=200,
    )
    assert counted["id"] is not None
    assert (await part_of(client, admin.headers, part["id"]))["stock"] == "3.000"
    latest = (await history(client, admin.headers, part["id"]))["movements"][0]
    # Sin motivo escrito: es un recuento, y guarda lo que se contó.
    assert (latest["kind"], latest["quantity"], latest["counted_stock"]) == (
        "adjustment",
        "-2.000",
        "3.000",
    )
    assert latest["note"] is None


@pytest.mark.asyncio
async def test_a_count_against_a_stock_that_changed_is_a_409(
    client: AsyncClient, admin: AdminSession
) -> None:
    """Quien contó veía 5; entre tanto entraron 2. El ajuste que pensaba hacer
    ya no deja lo contado: vuelve a mirar."""
    part = await create(client, admin.headers)
    await entry(client, admin.headers, part["id"], "5")
    await entry(client, admin.headers, part["id"], "2")
    response = await client.post(
        f"{PARTS}/{part['id']}/stock/count",
        json={"counted": "3", "expected": "5"},
        headers=admin.headers,
    )
    refused(response, "stock_changed")
    assert (await part_of(client, admin.headers, part["id"]))["stock"] == "7.000"


@pytest.mark.asyncio
async def test_a_count_that_matches_writes_nothing(
    client: AsyncClient, admin: AdminSession
) -> None:
    part = await create(client, admin.headers)
    await entry(client, admin.headers, part["id"], "5")
    counted = await move(
        client,
        admin.headers,
        part["id"],
        "count",
        {"counted": "5.000", "expected": "5"},
        status=200,
    )
    assert counted["id"] is None
    assert len((await history(client, admin.headers, part["id"]))["movements"]) == 1


# --- Anular (RNF-12) ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_wrong_entry_is_reversed_once_never_deleted(
    client: AsyncClient, admin: AdminSession
) -> None:
    part = await create(client, admin.headers)
    wrong = await entry(client, admin.headers, part["id"], "50")
    await entry(client, admin.headers, part["id"], "5")
    response = await client.post(
        f"{MOVEMENTS}/{wrong}/reverse",
        json={"note": "Eran 5, no 50"},
        headers=admin.headers,
    )
    assert response.status_code == 201, response.text
    reversal = response.json()["id"]
    assert (await part_of(client, admin.headers, part["id"]))["stock"] == "5.000"
    movements = (await history(client, admin.headers, part["id"]))["movements"]
    assert len(movements) == 3
    original = next(m for m in movements if m["id"] == wrong)
    assert original["reversed_by_id"] == reversal
    undone = next(m for m in movements if m["id"] == reversal)
    assert (undone["kind"], undone["quantity"], undone["reverses_id"]) == (
        "reversal",
        "-50.000",
        wrong,
    )

    again = await client.post(
        f"{MOVEMENTS}/{wrong}/reverse", json={"note": "Otra vez"}, headers=admin.headers
    )
    refused(again, "stock_movement_already_reversed")
    # Una anulación no se anula: el error se corrige con un movimiento nuevo.
    of_reversal = await client.post(
        f"{MOVEMENTS}/{reversal}/reverse", json={"note": "x"}, headers=admin.headers
    )
    refused(of_reversal, "stock_movement_not_reversible")


@pytest.mark.asyncio
async def test_a_reversal_needs_a_reason(
    client: AsyncClient, admin: AdminSession
) -> None:
    part = await create(client, admin.headers)
    wrong = await entry(client, admin.headers, part["id"], "5")
    for body in ({}, {"note": ""}, {"note": "   "}):
        response = await client.post(
            f"{MOVEMENTS}/{wrong}/reverse", json=body, headers=admin.headers
        )
        assert response.status_code == 422, body


# --- Incidencias (RF-94, RF-95) ------------------------------------------------


@pytest.mark.asyncio
async def test_negative_stock_is_allowed_and_flagged(
    client: AsyncClient, admin: AdminSession
) -> None:
    """RF-94: el stock puede quedar en negativo (se montó lo que aún no se
    registró). No se impide: se marca como incidencia."""
    part = await create(client, admin.headers, min_stock=None)
    await move(
        client,
        admin.headers,
        part["id"],
        "adjustments",
        {"quantity": "-1", "note": "Se montó sin dar entrada"},
    )
    seen = await part_of(client, admin.headers, part["id"])
    assert (seen["stock"], seen["stock_alert"]) == ("-1.000", "negative")


@pytest.mark.asyncio
async def test_below_the_minimum_is_flagged_and_listed_apart(
    client: AsyncClient, admin: AdminSession
) -> None:
    low = await create(client, admin.headers, min_stock="2")
    await entry(client, admin.headers, low["id"], "1")
    exact = await create(client, admin.headers, reference="EXACTA", min_stock="2")
    await entry(client, admin.headers, exact["id"], "2")
    await create(client, admin.headers, reference="SIN-MINIMO", min_stock=None)
    loose = await create(
        client, admin.headers, reference="TORNILLO", tracks_stock=False, min_stock=None
    )

    assert (await part_of(client, admin.headers, low["id"]))[
        "stock_alert"
    ] == "below_minimum"
    # Con el mínimo justo, todavía no.
    assert (await part_of(client, admin.headers, exact["id"]))["stock_alert"] is None
    # Lo que no se cuenta no tiene stock ni incidencias.
    seen_loose = await part_of(client, admin.headers, loose["id"])
    assert (seen_loose["stock"], seen_loose["stock_alert"]) == (None, None)

    alerts = await listed(client, admin.headers, alert="true")
    assert [p["reference"] for p in alerts["parts"]] == [low["reference"]]


# --- Qué se puede anotar ------------------------------------------------------


@pytest.mark.asyncio
async def test_stock_is_only_recorded_for_parts_that_count_it_and_are_current(
    client: AsyncClient, admin: AdminSession
) -> None:
    loose = await create(
        client, admin.headers, reference="TORNILLO", tracks_stock=False, min_stock=None
    )
    for what, body in (
        ("entries", {"quantity": "1", "unit_cost_cents": 1}),
        ("adjustments", {"quantity": "1", "note": "x"}),
        ("count", {"counted": "1", "expected": "0"}),
    ):
        response = await client.post(
            f"{PARTS}/{loose['id']}/stock/{what}", json=body, headers=admin.headers
        )
        refused(response, "part_stock_not_tracked")

    part = await create(client, admin.headers)
    wrong = await entry(client, admin.headers, part["id"], "3")
    await client.post(
        f"{PARTS}/{part['id']}/archive", json={"version": 1}, headers=admin.headers
    )
    response = await client.post(
        f"{PARTS}/{part['id']}/stock/entries",
        json={"quantity": "1", "unit_cost_cents": 1},
        headers=admin.headers,
    )
    refused(response, "part_archived")
    # Corregir lo que ya está en el libro sí se puede, archivada o no.
    response = await client.post(
        f"{MOVEMENTS}/{wrong}/reverse", json={"note": "Error"}, headers=admin.headers
    )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("what", "body"),
    [
        ("entries", {"quantity": "0", "unit_cost_cents": 1}),
        ("entries", {"quantity": "-1", "unit_cost_cents": 1}),
        ("entries", {"quantity": "1.0001", "unit_cost_cents": 1}),
        ("entries", {"quantity": "1", "unit_cost_cents": -1}),
        ("entries", {"quantity": "1"}),
        ("entries", {"quantity": "NaN", "unit_cost_cents": 1}),
        ("adjustments", {"quantity": "0", "note": "x"}),
        ("adjustments", {"quantity": "1", "note": ""}),
        ("adjustments", {"quantity": "1"}),
        ("count", {"counted": "-1", "expected": "0"}),
        ("count", {"counted": "1"}),
    ],
)
async def test_invalid_movements_are_a_422(
    client: AsyncClient, admin: AdminSession, what: str, body: dict[str, Any]
) -> None:
    part = await create(client, admin.headers)
    response = await client.post(
        f"{PARTS}/{part['id']}/stock/{what}", json=body, headers=admin.headers
    )
    assert response.status_code == 422, (what, body, response.text)


# --- Permisos y aislamiento ---------------------------------------------------


@pytest.mark.asyncio
async def test_a_mechanic_sees_the_stock_and_history_without_costs_and_records_nothing(
    client: AsyncClient, admin: AdminSession, mechanic: dict[str, str]
) -> None:
    part = await create(client, admin.headers)
    movement = await entry(client, admin.headers, part["id"], "5")
    assert (await part_of(client, mechanic, part["id"]))["stock"] == "5.000"
    (seen,) = (await history(client, mechanic, part["id"]))["movements"]
    assert seen["unit_cost_cents"] is None
    for path, body in (
        (
            f"{PARTS}/{part['id']}/stock/entries",
            {"quantity": "1", "unit_cost_cents": 1},
        ),
        (f"{PARTS}/{part['id']}/stock/adjustments", {"quantity": "1", "note": "x"}),
        (f"{PARTS}/{part['id']}/stock/count", {"counted": "1", "expected": "5"}),
        (f"{MOVEMENTS}/{movement}/reverse", {"note": "x"}),
    ):
        response = await client.post(path, json=body, headers=mechanic)
        assert response.status_code == 403, path
        assert response.json()["code"] == "not_allowed"


@pytest.mark.asyncio
async def test_the_stock_of_another_workshop_does_not_exist(
    client: AsyncClient, admin: AdminSession
) -> None:
    part = await create(client, admin.headers)
    movement = await entry(client, admin.headers, part["id"], "5")
    other = await open_workshop(client, "Taller Ajeno")
    response = await client.get(
        f"{PARTS}/{part['id']}/movements", headers=other.headers
    )
    assert (response.status_code, response.json()["code"]) == (404, "part_not_found")
    for what, body in (
        ("entries", {"quantity": "1", "unit_cost_cents": 1}),
        ("adjustments", {"quantity": "1", "note": "x"}),
        ("count", {"counted": "1", "expected": "5"}),
    ):
        response = await client.post(
            f"{PARTS}/{part['id']}/stock/{what}", json=body, headers=other.headers
        )
        assert (response.status_code, response.json()["code"]) == (
            404,
            "part_not_found",
        ), what
    response = await client.post(
        f"{MOVEMENTS}/{movement}/reverse", json={"note": "x"}, headers=other.headers
    )
    assert (response.status_code, response.json()["code"]) == (
        404,
        "stock_movement_not_found",
    )
    assert (await part_of(client, admin.headers, part["id"]))["stock"] == "5.000"


# --- Volumen de referencia (RNF-50) --------------------------------------------


@pytest_asyncio.fixture
async def busy_catalog(engines: Engines, admin: AdminSession) -> str:
    """5.000 piezas con 20 movimientos cada una (100.000 apuntes), el volumen
    de referencia de un taller mediano en diez años, y estadísticas al día. Una
    de cada diez, por debajo de su mínimo."""
    workshop = admin.invited.workshop_id
    async with engines.platform.begin() as conn:
        employee = await conn.scalar(
            text("SELECT id FROM employees WHERE workshop_id = :w"), {"w": workshop}
        )
        await conn.execute(
            text(
                "INSERT INTO parts (workshop_id, reference, description,"
                " sale_price_cents, vat_bp, min_stock)"
                " SELECT :w, 'REF-' || n, 'Pieza ' || n, 1000, 2100,"
                " CASE WHEN n % 10 = 0 THEN 100 END"
                " FROM generate_series(1, 5000) AS n"
            ),
            {"w": workshop},
        )
        await conn.execute(
            text(
                "INSERT INTO stock_movements (workshop_id, part_id, kind, quantity,"
                " unit_cost_cents, employee_id)"
                " SELECT :w, p.id, 'in', 1, 500, :e"
                " FROM parts p, generate_series(1, 20) WHERE p.workshop_id = :w"
            ),
            {"w": workshop, "e": employee},
        )
    async with engines.owner.connect() as conn:
        await conn.execute(text("ANALYZE parts"))
        await conn.execute(text("ANALYZE stock_movements"))
        await conn.commit()
    return workshop


@pytest.mark.asyncio
async def test_rnf50_the_catalog_with_its_stock_lists_fast_with_reference_volume(
    client: AsyncClient, admin: AdminSession, busy_catalog: str
) -> None:
    """RNF-50 (300 ms en el servidor) con 5.000 piezas y 100.000 movimientos.
    El stock de cada pieza es una suma que sirve el índice (taller, pieza) con
    la cantidad incluida; el listado de incidencias tiene que sumar las 5.000.
    Se mide por la API entera, con margen para la CI: aquí, una vez y sin
    calentar."""
    timings = {}
    for name, params in (("page", {}), ("alert", {"alert": "true", "limit": 100})):
        started = time.perf_counter()
        page = await listed(client, admin.headers, **params)
        timings[name] = time.perf_counter() - started
        assert page["parts"], name
    alerts = await listed(client, admin.headers, alert="true", limit=100)
    assert len(alerts["parts"]) == 100
    assert all(p["stock_alert"] == "below_minimum" for p in alerts["parts"])
    assert all(t < 1.5 for t in timings.values()), timings


@pytest.mark.asyncio
async def test_the_stock_sum_reads_only_the_index(
    admin: AdminSession, busy_catalog: str
) -> None:
    """La suma no lee la tabla del libro: le basta el índice (taller, pieza)
    con la cantidad incluida (Index Only Scan), bajo RLS."""
    from app.core import db
    from app.models import Part
    from app.repositories.parts import stock_expression

    statement = (
        select(Part.id, stock_expression())
        .limit(50)
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    try:
        async with db.workshop_transaction([UUID(busy_catalog)]) as session:
            plan = "\n".join(
                (await session.scalars(text(f"EXPLAIN {statement}"))).all()
            )
    finally:
        await db.engine.dispose()
    assert "Index Only Scan using ix_stock_movements_workshop_id_part_id" in plan, plan
    assert "Seq Scan on stock_movements" not in plan, plan
