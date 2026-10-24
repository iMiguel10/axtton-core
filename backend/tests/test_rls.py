"""Pruebas de RLS (arquitectura §4, R1–R4 y R7)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from tests.conftest import Engines, TwoWorkshops

WORKSHOP_TABLES = ("workshops", "clients", "vehicles", "work_orders")


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
        for table in WORKSHOP_TABLES:
            count = await conn.scalar(text(f"SELECT count(*) FROM {table}"))
            assert count == 0, table


@pytest.mark.asyncio
async def test_r1_owner_is_also_bound_by_rls_because_it_is_forced(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    async with engines.owner.connect() as conn:
        for table in WORKSHOP_TABLES:
            count = await conn.scalar(text(f"SELECT count(*) FROM {table}"))
            assert count == 0, table


@pytest.mark.asyncio
async def test_r2_with_workshop_a_only_rows_of_a_are_visible(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    async with engines.app.begin() as conn:
        await set_workshops(conn, two_workshops.a)
        # Sin WHERE a propósito: el filtro lo pone RLS.
        names = (await conn.scalars(text("SELECT name FROM clients"))).all()
        assert names == ["Cliente A"]
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
                text("INSERT INTO clients (workshop_id, name) VALUES (:w, 'Intruso')"),
                {"w": two_workshops.b},
            )


@pytest.mark.asyncio
async def test_composite_fk_rejects_linking_rows_of_two_workshops(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    """Incluso saltándose RLS (plataforma), la FK compuesta impide mezclar talleres."""
    async with engines.platform.begin() as conn:
        client_of_b = await conn.scalar(
            text("SELECT id FROM clients WHERE workshop_id = :b"),
            {"b": two_workshops.b},
        )
        vehicle_of_a = await conn.scalar(
            text("SELECT id FROM vehicles WHERE workshop_id = :a"),
            {"a": two_workshops.a},
        )
        with pytest.raises(DBAPIError, match="foreign key"):
            await conn.execute(
                text(
                    "INSERT INTO work_orders (workshop_id, vehicle_id, client_id)"
                    " VALUES (:a, :v, :c)"
                ),
                {"a": two_workshops.a, "v": vehicle_of_a, "c": client_of_b},
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
    assert len(rows) >= len(WORKSHOP_TABLES)
    for name, enabled, forced, has_policy in rows:
        assert enabled and forced and has_policy, name


@pytest.mark.asyncio
async def test_r7_workshop_does_not_stick_to_a_pooled_connection(
    two_workshops: TwoWorkshops,
) -> None:
    """Con un pool de UNA conexión, la segunda transacción reutiliza la primera."""
    import os

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
            assert await conn.scalar(text("SELECT count(*) FROM clients")) == 1

        async with engine.begin() as conn:
            second_pid = await conn.scalar(text("SELECT pg_backend_pid()"))
            visible = await conn.scalar(text("SELECT count(*) FROM clients"))

        assert second_pid == first_pid, "la prueba necesita la misma conexión"
        assert visible == 0
    finally:
        await engine.dispose()
