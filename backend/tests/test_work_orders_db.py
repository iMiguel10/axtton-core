"""Las órdenes en la base de datos, sin pasar por el código (arquitectura §3, §4).

El invariante 5, el historial append-only, la numeración y el año del taller no
dependen de que el service lo haga bien: aquí se intenta romper cada garantía
directamente con SQL.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.conftest import Engines, TwoWorkshops
from tests.test_rls import set_workshops


@dataclass(frozen=True)
class Order:
    workshop_id: UUID
    order_id: UUID


@pytest_asyncio.fixture
async def order(engines: Engines, two_workshops: TwoWorkshops) -> Order:
    """Una orden recibida del taller A, con su primer cambio, escrita como lo
    hace el service."""
    a = two_workshops.a
    async with engines.platform.begin() as conn:
        client = await conn.scalar(
            text(
                "INSERT INTO clients (workshop_id, name, phone)"
                " VALUES (:w, 'María', '600') RETURNING id"
            ),
            {"w": a},
        )
        vehicle = await conn.scalar(
            text(
                "INSERT INTO vehicles (workshop_id, plate, plate_normalized)"
                " VALUES (:w, '1', '1') RETURNING id"
            ),
            {"w": a},
        )
        order_id = await conn.scalar(
            text(
                "INSERT INTO work_orders"
                " (workshop_id, year, number, type, vehicle_id, client_id, status)"
                " VALUES (:w, 2026, 1, 'breakdown', :v, :c, 'received') RETURNING id"
            ),
            {"w": a, "v": vehicle, "c": client},
        )
        await conn.execute(
            text(
                "INSERT INTO work_order_status_changes"
                " (workshop_id, work_order_id, to_status, cause)"
                " VALUES (:w, :o, 'received', 'opened')"
            ),
            {"w": a, "o": order_id},
        )
    return Order(a, order_id)


async def change(
    conn: AsyncConnection,
    order: Order,
    to: str,
    cause: str = "manual",
    from_: str | None = "received",
) -> None:
    await conn.execute(
        text(
            "INSERT INTO work_order_status_changes"
            " (workshop_id, work_order_id, from_status, to_status, cause)"
            " VALUES (:w, :o, :f, :t, :c)"
        ),
        {"w": order.workshop_id, "o": order.order_id, "f": from_, "t": to, "c": cause},
    )


# --- Invariante 5 ------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_status_cannot_change_without_its_change_in_the_history(
    engines: Engines, order: Order
) -> None:
    """Se comprueba al confirmar (trigger diferido): la transacción entera falla."""
    with pytest.raises(DBAPIError, match="its last change says received"):
        async with engines.platform.begin() as conn:
            await conn.execute(
                text("UPDATE work_orders SET status = 'ready' WHERE id = :o"),
                {"o": order.order_id},
            )


@pytest.mark.asyncio
async def test_a_change_cannot_be_written_without_moving_the_order(
    engines: Engines, order: Order
) -> None:
    with pytest.raises(
        DBAPIError, match="has status received but its last change says diagnosing"
    ):
        async with engines.platform.begin() as conn:
            await change(conn, order, "diagnosing")


@pytest.mark.asyncio
async def test_status_and_change_together_are_accepted_in_any_order(
    engines: Engines, order: Order
) -> None:
    """Prueba de control: lo que hace el service pasa, se escriba antes la orden
    o antes el cambio, porque solo se mira al final."""
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE work_orders SET status = 'diagnosing' WHERE id = :o"),
            {"o": order.order_id},
        )
        await change(conn, order, "diagnosing")
    async with engines.platform.begin() as conn:
        await change(conn, order, "in_repair", from_="diagnosing")
        await conn.execute(
            text("UPDATE work_orders SET status = 'in_repair' WHERE id = :o"),
            {"o": order.order_id},
        )
        status = await conn.scalar(
            text("SELECT status FROM work_orders WHERE id = :o"), {"o": order.order_id}
        )
    assert status == "in_repair"


@pytest.mark.asyncio
async def test_an_order_cannot_exist_without_its_first_change(
    engines: Engines, order: Order, two_workshops: TwoWorkshops
) -> None:
    with pytest.raises(
        DBAPIError, match="has status received but its last change says <NULL>"
    ):
        async with engines.platform.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO work_orders"
                    " (workshop_id, year, number, type, vehicle_id, client_id, status)"
                    " SELECT workshop_id, year, 2, type, vehicle_id, client_id, status"
                    " FROM work_orders WHERE id = :o"
                ),
                {"o": order.order_id},
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("from_", "cause"),
    [("received", "opened"), (None, "manual")],
)
async def test_only_the_opening_comes_from_no_status(
    engines: Engines, order: Order, from_: str | None, cause: str
) -> None:
    async with engines.platform.begin() as conn:
        with pytest.raises(DBAPIError, match="opened_from_nothing"):
            await change(conn, order, "received", cause=cause, from_=from_)


# --- Append-only y sin borrados (RNF-12) ------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE work_order_status_changes SET to_status = 'ready'",
        "DELETE FROM work_order_status_changes",
        "TRUNCATE work_order_status_changes",
        "DELETE FROM work_orders",
        "TRUNCATE work_orders",
        "DELETE FROM work_order_counters",
    ],
)
async def test_the_app_role_cannot_rewrite_the_history_or_delete_orders(
    engines: Engines, order: Order, statement: str
) -> None:
    async with engines.app.begin() as conn:
        await set_workshops(conn, order.workshop_id)
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text(statement))


# --- Numeración (RF-21) ------------------------------------------------------


@pytest.mark.asyncio
async def test_two_orders_cannot_share_a_number(engines: Engines, order: Order) -> None:
    """La última red si el contador fallara: (taller, año, número) es único."""
    with pytest.raises(DBAPIError, match="uq_work_orders_workshop_id_year_number"):
        async with engines.platform.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO work_orders"
                    " (workshop_id, year, number, type, vehicle_id, client_id, status)"
                    " SELECT workshop_id, year, number, type, vehicle_id, client_id, status"
                    " FROM work_orders WHERE id = :o"
                ),
                {"o": order.order_id},
            )


@pytest.mark.asyncio
async def test_the_counter_only_grows(engines: Engines, order: Order) -> None:
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO work_order_counters (workshop_id, year, last_number)"
                " VALUES (:w, 2026, 5)"
            ),
            {"w": order.workshop_id},
        )
    for change_sql in ("last_number = 4", "last_number = 5", "year = 2027"):
        async with engines.app.begin() as conn:
            await set_workshops(conn, order.workshop_id)
            with pytest.raises(DBAPIError, match="only grow"):
                await conn.execute(text(f"UPDATE work_order_counters SET {change_sql}"))


@pytest.mark.asyncio
async def test_the_counter_is_per_workshop_and_year(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    from app.core import db
    from app.repositories import work_orders as order_repo

    try:
        numbers = []
        for workshop, year in (
            (two_workshops.a, 2026),
            (two_workshops.a, 2026),
            (two_workshops.b, 2026),
            (two_workshops.a, 2027),
        ):
            async with db.workshop_transaction([workshop]) as session:
                numbers.append(await order_repo.next_number(session, workshop, year))
    finally:
        await db.engine.dispose()
    assert numbers == [1, 2, 1, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("timezone", "instant", "year"),
    [
        # 23:30 del 31 de diciembre en UTC ya es 1 de enero en Madrid.
        ("Europe/Madrid", datetime(2026, 12, 31, 23, 30, tzinfo=UTC), 2027),
        ("Europe/Madrid", datetime(2026, 12, 31, 22, 30, tzinfo=UTC), 2026),
        # Y al revés: el 1 de enero en UTC aún es 31 de diciembre en Canarias...
        ("Atlantic/Canary", datetime(2027, 1, 1, 0, 30, tzinfo=UTC), 2027),
        # ...pero no en Nueva York.
        ("America/New_York", datetime(2027, 1, 1, 0, 30, tzinfo=UTC), 2026),
    ],
)
async def test_the_year_of_an_order_is_the_workshops_year(
    engines: Engines,
    two_workshops: TwoWorkshops,
    timezone: str,
    instant: datetime,
    year: int,
) -> None:
    from app.core import db
    from app.repositories import work_orders as order_repo

    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE workshops SET timezone = :tz WHERE id = :w"),
            {"tz": timezone, "w": two_workshops.a},
        )
    try:
        async with db.workshop_transaction([two_workshops.a]) as session:
            got = await order_repo.local_year(session, two_workshops.a, instant)
    finally:
        await db.engine.dispose()
    assert got == year
