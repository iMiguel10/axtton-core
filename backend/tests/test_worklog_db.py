"""Diagnóstico, notas y trabajos en la base de datos, sin pasar por el código.

Que nada de esto se reescriba lo garantizan los permisos de axtton_app y un
trigger: aquí se intenta romper cada uno con SQL (migración 0007worklog).
"""

from dataclasses import dataclass
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import Engines, TwoWorkshops
from tests.test_rls import set_workshops
from tests.test_work_orders_db import Order, seed_order


@dataclass(frozen=True)
class Logged:
    order: Order
    admin: UUID
    entry_id: UUID


@pytest_asyncio.fixture
async def logged(engines: Engines, two_workshops: TwoWorkshops) -> Logged:
    """La orden del taller A con una versión de diagnóstico, una nota y un trabajo."""
    order = await seed_order(engines, two_workshops)
    admin = two_workshops.admin_a
    params = {"w": order.workshop_id, "o": order.order_id, "e": admin}
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO diagnosis_versions"
                " (workshop_id, work_order_id, version_no, text, employee_id)"
                " VALUES (:w, :o, 1, 'Pastillas', :e)"
            ),
            params,
        )
        await conn.execute(
            text(
                "INSERT INTO internal_notes (workshop_id, work_order_id, employee_id, body)"
                " VALUES (:w, :o, :e, 'Ojo')"
            ),
            params,
        )
        entry_id = await conn.scalar(
            text(
                "INSERT INTO work_entries (workshop_id, work_order_id, employee_id,"
                " recorded_by_employee_id, description, worked_on)"
                " VALUES (:w, :o, :e, :e, 'Pastillas', current_date) RETURNING id"
            ),
            params,
        )
    return Logged(order, admin, entry_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE diagnosis_versions SET text = 'Otro'",
        "DELETE FROM diagnosis_versions",
        "UPDATE internal_notes SET body = 'Otro'",
        "DELETE FROM internal_notes",
        "UPDATE work_entries SET description = 'Otro'",
        "UPDATE work_entries SET hours = 8",
        "DELETE FROM work_entries",
        "TRUNCATE work_entries",
    ],
)
async def test_the_app_role_cannot_rewrite_the_worklog(
    engines: Engines, logged: Logged, statement: str
) -> None:
    async with engines.app.begin() as conn:
        await set_workshops(conn, logged.order.workshop_id)
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text(statement))


@pytest.mark.asyncio
async def test_the_app_role_can_void_a_work_entry_once(
    engines: Engines, logged: Logged
) -> None:
    void = (
        "UPDATE work_entries SET voided_at = clock_timestamp(),"
        " voided_by_employee_id = :e WHERE id = :id"
    )
    params = {"e": logged.admin, "id": logged.entry_id}
    async with engines.app.begin() as conn:
        await set_workshops(conn, logged.order.workshop_id)
        assert (await conn.execute(text(void), params)).rowcount == 1
    async with engines.app.begin() as conn:
        await set_workshops(conn, logged.order.workshop_id)
        with pytest.raises(DBAPIError, match="can only be voided, once"):
            await conn.execute(text(void), params)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["owner", "platform"])
async def test_a_work_entry_cannot_be_rewritten_with_any_role(
    engines: Engines, logged: Logged, role: str
) -> None:
    engine = engines.owner if role == "owner" else engines.platform
    async with engine.begin() as conn:
        await set_workshops(conn, logged.order.workshop_id)
        with pytest.raises(DBAPIError, match="can only be voided, once"):
            await conn.execute(
                text("UPDATE work_entries SET description = 'Otro' WHERE id = :id"),
                {"id": logged.entry_id},
            )


@pytest.mark.asyncio
async def test_a_voided_entry_says_by_whom(engines: Engines, logged: Logged) -> None:
    async with engines.platform.begin() as conn:
        with pytest.raises(DBAPIError, match="ck_work_entries_voided_by_whom"):
            await conn.execute(
                text(
                    "UPDATE work_entries SET voided_at = clock_timestamp() WHERE id = :id"
                ),
                {"id": logged.entry_id},
            )


@pytest.mark.asyncio
async def test_two_diagnoses_cannot_share_a_version_number(
    engines: Engines, logged: Logged
) -> None:
    """El índice único es el bloqueo optimista del diagnóstico (RNF-15)."""
    async with engines.app.begin() as conn:
        await set_workshops(conn, logged.order.workshop_id)
        with pytest.raises(
            DBAPIError, match="uq_diagnosis_versions_work_order_id_version_no"
        ):
            await conn.execute(
                text(
                    "INSERT INTO diagnosis_versions"
                    " (workshop_id, work_order_id, version_no, text, employee_id)"
                    " VALUES (:w, :o, 1, 'Otra', :e)"
                ),
                {
                    "w": logged.order.workshop_id,
                    "o": logged.order.order_id,
                    "e": logged.admin,
                },
            )
