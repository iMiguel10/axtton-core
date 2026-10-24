"""Pruebas de RLS (arquitectura §4, R1–R5 y R7) sobre las tablas de F1."""

import os
import subprocess

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from tests.conftest import Engines, TwoWorkshops

# Tablas de taller con datos en el fixture two_workshops.
SEEDED_WORKSHOP_TABLES = ("workshops", "employees")


async def set_workshops(conn: AsyncConnection, *workshop_ids: object) -> None:
    ids = "{" + ",".join(str(i) for i in workshop_ids) + "}"
    await conn.execute(
        text("SELECT set_config('app.workshop_ids', :ids, true)"), {"ids": ids}
    )


@pytest.mark.asyncio
async def test_r1_without_workshop_app_sees_no_rows(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    async with engines.app.connect() as conn:
        for table in SEEDED_WORKSHOP_TABLES:
            count = await conn.scalar(text(f"SELECT count(*) FROM {table}"))
            assert count == 0, table


@pytest.mark.asyncio
async def test_r1_owner_is_also_bound_by_rls_because_it_is_forced(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    async with engines.owner.connect() as conn:
        for table in SEEDED_WORKSHOP_TABLES:
            count = await conn.scalar(text(f"SELECT count(*) FROM {table}"))
            assert count == 0, table


@pytest.mark.asyncio
async def test_r2_with_workshop_a_only_rows_of_a_are_visible(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    async with engines.app.begin() as conn:
        await set_workshops(conn, two_workshops.a)
        # Sin WHERE a propósito: el filtro lo pone RLS.
        names = (await conn.scalars(text("SELECT name FROM employees"))).all()
        assert names == ["Admin A"]
        workshops = (await conn.scalars(text("SELECT id FROM workshops"))).all()
        assert workshops == [two_workshops.a]


@pytest.mark.asyncio
async def test_r3_inserting_a_row_of_another_workshop_is_rejected(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    async with engines.app.begin() as conn:
        await set_workshops(conn, two_workshops.a)
        with pytest.raises(DBAPIError, match="row-level security policy"):
            await conn.execute(
                text(
                    "INSERT INTO employees (workshop_id, name, role)"
                    " VALUES (:w, 'Intruso', 'admin')"
                ),
                {"w": two_workshops.b},
            )


@pytest.mark.asyncio
async def test_composite_fk_rejects_linking_rows_of_two_workshops(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    """Incluso saltándose RLS (plataforma), la FK compuesta impide mezclar talleres:
    una invitación del taller A no puede apuntar a un empleado del taller B."""
    async with engines.platform.begin() as conn:
        with pytest.raises(DBAPIError, match="foreign key"):
            await conn.execute(
                text(
                    "INSERT INTO invitations"
                    " (workshop_id, employee_id, email, token_hash, expires_at)"
                    " VALUES (:a, :employee_of_b, 'x@example.com', 'x',"
                    " clock_timestamp() + interval '7 days')"
                ),
                {"a": two_workshops.a, "employee_of_b": two_workshops.admin_b},
            )


@pytest.mark.asyncio
async def test_r4_every_table_with_workshop_column_has_forced_rls_and_policy(
    engines: Engines,
) -> None:
    """Recorre el catálogo: una tabla nueva sin RLS hace fallar esta prueba."""
    query = text(
        """
        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
               EXISTS (
                   SELECT 1 FROM pg_policies p
                   WHERE p.tablename = c.relname AND p.policyname = 'workshop_isolation'
               ) AS has_policy
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
          AND (c.relname = 'workshops' OR EXISTS (
              SELECT 1 FROM pg_attribute a
              WHERE a.attrelid = c.oid AND a.attname = 'workshop_id' AND NOT a.attisdropped
          ))
        """
    )
    async with engines.platform.connect() as conn:
        rows = (await conn.execute(query)).all()
    # Prueba de control: si la consulta no encontrara tablas, pasaría sin comprobar nada.
    assert {row[0] for row in rows} >= {
        "workshops",
        "employees",
        "invitations",
        "audit_log",
    }
    for name, enabled, forced, has_policy in rows:
        assert enabled and forced and has_policy, name


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_log SET action = 'otra'", "DELETE FROM audit_log"],
)
async def test_r5_audit_log_cannot_be_updated_or_deleted(
    engines: Engines, two_workshops: TwoWorkshops, statement: str
) -> None:
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("INSERT INTO audit_log (workshop_id, action) VALUES (:w, 'prueba')"),
            {"w": two_workshops.a},
        )
    # Ni siquiera el rol de plataforma, que se salta RLS.
    async with engines.platform.begin() as conn:
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text(statement))


@pytest.mark.asyncio
async def test_platform_audit_entries_are_invisible_to_any_workshop(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    """Las acciones de plataforma (workshop_id nulo) no las ve ningún taller."""
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("INSERT INTO audit_log (action) VALUES ('workshop_created')")
        )
    async with engines.app.begin() as conn:
        await set_workshops(conn, two_workshops.a, two_workshops.b)
        assert await conn.scalar(text("SELECT count(*) FROM audit_log")) == 0


@pytest.mark.asyncio
async def test_r7_workshop_does_not_stick_to_a_pooled_connection(
    two_workshops: TwoWorkshops,
) -> None:
    """Con un pool de UNA conexión, la segunda transacción reutiliza la primera."""
    engine = create_async_engine(
        os.environ["DATABASE_URL"],
        poolclass=AsyncAdaptedQueuePool,
        pool_size=1,
        max_overflow=0,
    )
    try:
        async with engine.begin() as conn:
            await set_workshops(conn, two_workshops.a)
            first_pid = await conn.scalar(text("SELECT pg_backend_pid()"))
            assert await conn.scalar(text("SELECT count(*) FROM employees")) == 1

        async with engine.begin() as conn:
            second_pid = await conn.scalar(text("SELECT pg_backend_pid()"))
            visible = await conn.scalar(text("SELECT count(*) FROM employees"))

        assert second_pid == first_pid, "la prueba necesita la misma conexión"
        assert visible == 0
    finally:
        await engine.dispose()


def test_models_match_the_migrations() -> None:
    """`alembic check` compara los modelos con la base migrada.

    Si alguien cambia un modelo sin escribir su migración (o al revés), falla.
    No ve RLS, políticas ni triggers: eso lo vigilan R4 y las demás pruebas.
    """
    result = subprocess.run(
        ["alembic", "check"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
