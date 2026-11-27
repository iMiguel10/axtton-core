"""Las piezas usadas y sus salidas en la base de datos, sin pasar por el código
(F7 paso 3, migración 0029usedparts).

Una pieza usada solo cambia al quitarla, una vez, con cualquier rol, y nunca se
borra. La salida de stock de una pieza usada es exactamente la suya (pieza,
orden, cantidad, montada), una sola, y solo se deshace por ella.
"""

from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.conftest import Engines, TwoWorkshops
from tests.test_rls import set_workshops
from tests.test_stock_db import roles, seed_part
from tests.test_work_orders_db import Order, seed_order

USED = (
    "INSERT INTO used_parts (workshop_id, work_order_id, part_id, quantity,"
    " reference, description, part_condition, employee_id)"
    " VALUES (:w, :o, :p, 2, 'BAT', 'Batería', 'new', :e) RETURNING id"
)
MOVE = (
    "INSERT INTO stock_movements (workshop_id, part_id, kind, quantity, note,"
    " reverses_id, work_order_id, used_part_id, employee_id)"
    " VALUES (:w, :p, :kind, :quantity, :note, :reverses, :o, :u, :e) RETURNING id"
)


async def run(
    engines: Engines, role: str, workshop: UUID, sql: str, **params: Any
) -> Any:
    async with roles(engines)[role].begin() as conn:
        await set_workshops(conn, workshop)
        result = await conn.execute(text(sql), params)
        return result.scalar() if result.returns_rows else None


class Mounted:
    def __init__(self, order: Order, part: UUID, used: UUID, employee: UUID) -> None:
        self.order, self.part, self.used, self.employee = order, part, used, employee

    @property
    def workshop(self) -> UUID:
        return self.order.workshop_id

    def params(self, **overrides: Any) -> dict[str, Any]:
        base = {
            "w": self.workshop,
            "p": self.part,
            "o": self.order.order_id,
            "u": self.used,
            "e": self.employee,
            "note": None,
            "reverses": None,
        }
        return base | overrides


@pytest_asyncio.fixture
async def mounted(engines: Engines, two_workshops: TwoWorkshops) -> Mounted:
    """Dos baterías montadas en la orden de María, aún sin salida de stock."""
    order = await seed_order(engines, two_workshops)
    part = await seed_part(engines, two_workshops.a)
    used = await run(
        engines,
        "app",
        two_workshops.a,
        USED,
        w=two_workshops.a,
        o=order.order_id,
        p=part,
        e=two_workshops.admin_a,
    )
    return Mounted(order, part, used, two_workshops.admin_a)


async def outflow(engines: Engines, m: Mounted, **overrides: Any) -> UUID:
    movement: UUID = await run(
        engines,
        "app",
        m.workshop,
        MOVE,
        **m.params(kind="out", quantity="-2") | overrides,
    )
    return movement


async def row(engines: Engines, m: Mounted) -> tuple[Any, ...]:
    async with engines.platform.connect() as conn:
        result = await conn.execute(
            text("SELECT * FROM used_parts WHERE id = :u"), {"u": m.used}
        )
        return tuple(result.one())


REMOVE = (
    "UPDATE used_parts SET removed_at = now(), removed_by_employee_id = :e"
    " WHERE id = :u"
)


# --- La pieza usada: solo se quita, una vez -------------------------------------

CHANGES = [
    "UPDATE used_parts SET quantity = 5 WHERE id = :u",
    "UPDATE used_parts SET description = 'Otra' WHERE id = :u",
    "UPDATE used_parts SET warranty_months = 36 WHERE id = :u",
    "UPDATE used_parts SET created_at = created_at WHERE id = :u",
    (
        "UPDATE used_parts SET quantity = 5, removed_at = now(),"
        " removed_by_employee_id = :e WHERE id = :u"
    ),
    "DELETE FROM used_parts WHERE id = :u",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform", "owner"])
@pytest.mark.parametrize("statement", CHANGES)
async def test_a_used_part_does_not_change_nor_go_with_any_role(
    engines: Engines, mounted: Mounted, role: str, statement: str
) -> None:
    """A la aplicación la para el permiso por columna (salvo quitarla); a la
    plataforma y al dueño, el trigger."""
    before = await row(engines, mounted)
    with pytest.raises(DBAPIError, match="only be removed, once|permission denied"):
        await run(
            engines,
            role,
            mounted.workshop,
            statement,
            u=mounted.used,
            e=mounted.employee,
        )
    assert await row(engines, mounted) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["platform", "owner"])
async def test_the_trigger_stops_what_the_permissions_let_through(
    engines: Engines, mounted: Mounted, role: str
) -> None:
    """Sin permiso por columna (plataforma y dueño), lo que para un cambio es el
    trigger, con su mensaje: si faltara, esto pasaría."""
    with pytest.raises(DBAPIError, match="only be removed, once"):
        await run(
            engines,
            role,
            mounted.workshop,
            "UPDATE used_parts SET quantity = 5 WHERE id = :u",
            u=mounted.used,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform", "owner"])
async def test_a_used_part_is_removed_once_and_never_put_back(
    engines: Engines, mounted: Mounted, role: str
) -> None:
    await run(
        engines, role, mounted.workshop, REMOVE, u=mounted.used, e=mounted.employee
    )
    removed = await row(engines, mounted)
    for statement in (
        REMOVE,
        (
            "UPDATE used_parts SET removed_at = NULL, removed_by_employee_id = NULL"
            " WHERE id = :u"
        ),
    ):
        with pytest.raises(DBAPIError, match="only be removed, once"):
            await run(
                engines,
                role,
                mounted.workshop,
                statement,
                u=mounted.used,
                e=mounted.employee,
            )
    assert await row(engines, mounted) == removed


# --- Su salida de stock ----------------------------------------------------------


@pytest.mark.asyncio
async def test_the_outflow_of_a_used_part_is_exactly_its_own(
    engines: Engines, two_workshops: TwoWorkshops, mounted: Mounted
) -> None:
    other_part = await seed_part(engines, two_workshops.a, "OTRA")
    other_order = await seed_order_number_two(engines, two_workshops)
    for overrides, stopped_by in (
        ({"quantity": "-1"}, "its quantity, while mounted"),
        ({"p": other_part}, "its own part in its own order"),
        ({"o": other_order}, "its own part in its own order"),
    ):
        with pytest.raises(DBAPIError, match=stopped_by):
            await outflow(engines, mounted, **overrides)
    with pytest.raises(IntegrityError, match="check constraint"):
        # Una salida sin pieza usada.
        await outflow(engines, mounted, u=None, o=None)
    await outflow(engines, mounted)
    with pytest.raises(IntegrityError, match="uq_stock_movements_used_part_id_out"):
        await outflow(engines, mounted)


@pytest.mark.asyncio
async def test_a_removed_part_takes_nothing_out(
    engines: Engines, mounted: Mounted
) -> None:
    await run(
        engines, "app", mounted.workshop, REMOVE, u=mounted.used, e=mounted.employee
    )
    with pytest.raises(DBAPIError, match="its quantity, while mounted"):
        await outflow(engines, mounted)


@pytest.mark.asyncio
async def test_an_outflow_is_only_reversed_through_its_used_part(
    engines: Engines, mounted: Mounted
) -> None:
    out = await outflow(engines, mounted)
    reversal = {"kind": "reversal", "quantity": "2", "reverses": out}
    # A mano, sin la pieza usada: el trigger de la anulación lo para.
    with pytest.raises(DBAPIError, match="must undo exactly its movement"):
        await run(
            engines,
            "app",
            mounted.workshop,
            MOVE,
            **mounted.params(**reversal, u=None, o=None, note="a mano"),
        )
    # Por su pieza usada, sin motivo escrito: su origen la explica.
    await run(engines, "app", mounted.workshop, MOVE, **mounted.params(**reversal))


async def seed_order_number_two(engines: Engines, two_workshops: TwoWorkshops) -> UUID:
    """Otra orden del mismo taller y del mismo coche."""
    async with engines.platform.begin() as conn:
        order: UUID = await conn.scalar(
            text(
                "INSERT INTO work_orders (workshop_id, year, number, type,"
                " vehicle_id, client_id, status)"
                " SELECT workshop_id, year, 2, type, vehicle_id, client_id, status"
                " FROM work_orders WHERE workshop_id = :w RETURNING id"
            ),
            {"w": two_workshops.a},
        )
        await conn.execute(
            text(
                "INSERT INTO work_order_status_changes"
                " (workshop_id, work_order_id, to_status, cause)"
                " VALUES (:w, :o, 'received', 'opened')"
            ),
            {"w": two_workshops.a, "o": order},
        )
    return order
