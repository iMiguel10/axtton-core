"""RLS y permisos sobre TODAS las tablas de taller (arquitectura §4).

test_rls.py comprueba R1 y R2 solo con `workshops` y `employees`, porque el
fixture two_workshops no siembra más. Aquí cada tabla de taller lleva filas de A
y de B (también `invitations` y `audit_log`), y se comprueba lo mismo tabla a
tabla, además de R5 con el rol de la aplicación, que test_rls.py solo prueba con
el de plataforma.
"""

import os
from dataclasses import dataclass
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import Engines, TwoWorkshops
from tests.test_rls import set_workshops

# Tabla de taller -> columna con la que RLS la separa. Si aparece una tabla de
# taller nueva, test_every_workshop_table_is_seeded_here obliga a añadirla.
WORKSHOP_TABLES = {
    "workshops": "id",
    "employees": "workshop_id",
    "invitations": "workshop_id",
    "audit_log": "workshop_id",
    "clients": "workshop_id",
    "vehicles": "workshop_id",
    "vehicle_ownerships": "workshop_id",
}

# Tablas sobre las que axtton_app no tiene DELETE: no se borran nunca, ni por un
# fallo de la aplicación (sus propias pruebas de permisos, más abajo y en
# test_ownerships_db.py).
NO_DELETE = {"audit_log", "workshops", "clients", "vehicles", "vehicle_ownerships"}
# La columna que axtton_app puede actualizar, si no puede todas.
UPDATABLE_COLUMN = {"vehicle_ownerships": "ended_at"}


@dataclass(frozen=True)
class Seeded:
    workshops: TwoWorkshops
    # Filas de cada tabla por taller: {"invitations": {a: 1, b: 1}, ...}
    counts: dict[str, dict[UUID, int]]


@pytest_asyncio.fixture
async def seeded(engines: Engines, two_workshops: TwoWorkshops) -> Seeded:
    """Dos talleres con filas en cada tabla de taller, más una fila de plataforma
    en audit_log (workshop_id nulo), que ningún taller debe ver."""
    async with engines.platform.begin() as conn:
        for workshop, employee in (
            (two_workshops.a, two_workshops.admin_a),
            (two_workshops.b, two_workshops.admin_b),
        ):
            await conn.execute(
                text(
                    "INSERT INTO invitations"
                    " (workshop_id, employee_id, email, token_hash, expires_at)"
                    " VALUES (:w, :e, 'x@example.com', :h,"
                    " clock_timestamp() + interval '7 days')"
                ),
                {"w": workshop, "e": employee, "h": workshop.bytes},
            )
            await conn.execute(
                text(
                    "INSERT INTO audit_log (workshop_id, action, target_id)"
                    " VALUES (:w, 'employee_created', :e)"
                ),
                {"w": workshop, "e": employee},
            )
            client = await conn.scalar(
                text(
                    "INSERT INTO clients (workshop_id, name, phone)"
                    " VALUES (:w, 'Cliente', '600') RETURNING id"
                ),
                {"w": workshop},
            )
            vehicle = await conn.scalar(
                text(
                    "INSERT INTO vehicles (workshop_id, plate, plate_normalized)"
                    " VALUES (:w, '1234 BCD', '1234BCD') RETURNING id"
                ),
                {"w": workshop},
            )
            await conn.execute(
                text(
                    "INSERT INTO vehicle_ownerships"
                    " (workshop_id, vehicle_id, client_id, started_at)"
                    " VALUES (:w, :v, :c, clock_timestamp())"
                ),
                {"w": workshop, "v": vehicle, "c": client},
            )
        await conn.execute(
            text("INSERT INTO audit_log (action) VALUES ('workshop_created')")
        )
    one_each = {two_workshops.a: 1, two_workshops.b: 1}
    return Seeded(two_workshops, dict.fromkeys(WORKSHOP_TABLES, one_each))


@pytest.mark.asyncio
async def test_every_workshop_table_is_seeded_here(engines: Engines) -> None:
    """Prueba de control: si aparece una tabla con workshop_id, esta lista (y por
    tanto R1/R2/R3 tabla a tabla) tiene que crecer con ella."""
    async with engines.platform.connect() as conn:
        found = set(
            (
                await conn.scalars(
                    text(
                        "SELECT DISTINCT table_name FROM information_schema.columns"
                        " WHERE table_schema = 'public' AND column_name = 'workshop_id'"
                    )
                )
            ).all()
        )
    assert found | {"workshops"} == set(WORKSHOP_TABLES)


@pytest.mark.asyncio
@pytest.mark.parametrize("table", WORKSHOP_TABLES)
async def test_r1_without_workshop_the_app_sees_no_row_of_any_table(
    engines: Engines, seeded: Seeded, table: str
) -> None:
    async with engines.platform.connect() as conn:
        # Prueba de control: la tabla tiene filas (si no, cero no probaría nada).
        assert await conn.scalar(text(f"SELECT count(*) FROM {table}"))
    async with engines.app.connect() as conn:
        assert await conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("table", WORKSHOP_TABLES)
async def test_r1_an_empty_workshop_setting_also_sees_nothing(
    engines: Engines, seeded: Seeded, table: str
) -> None:
    """set_config con '' (lo que deja un SET LOCAL ya revertido) falla cerrado."""
    async with engines.app.begin() as conn:
        await conn.execute(text("SELECT set_config('app.workshop_ids', '', true)"))
        assert await conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("table", "column"), WORKSHOP_TABLES.items())
async def test_r2_with_workshop_a_every_table_returns_only_rows_of_a(
    engines: Engines, seeded: Seeded, table: str, column: str
) -> None:
    a = seeded.workshops.a
    async with engines.app.begin() as conn:
        await set_workshops(conn, a)
        # Sin WHERE a propósito: el filtro lo pone RLS.
        owners = (await conn.scalars(text(f"SELECT {column} FROM {table}"))).all()
    assert owners == [a] * seeded.counts[table][a], table


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("table", "column"),
    # audit_log y workshops no están: axtton_app ni siquiera tiene permiso de
    # UPDATE sobre ellas (R5 y test_the_app_cannot_change_any_workshop). De las
    # de NO_DELETE, solo se prueba el UPDATE: el DELETE lo para el permiso.
    [(t, c) for t, c in WORKSHOP_TABLES.items() if t not in {"audit_log", "workshops"}],
)
async def test_rows_of_b_cannot_be_updated_or_deleted_from_a(
    engines: Engines, seeded: Seeded, table: str, column: str
) -> None:
    """RLS también filtra UPDATE y DELETE: desde A, las filas de B no existen."""
    a, b = seeded.workshops.a, seeded.workshops.b
    async with engines.app.begin() as conn:
        await set_workshops(conn, a)
        field = UPDATABLE_COLUMN.get(table, "created_at")
        touched = await conn.execute(
            text(f"UPDATE {table} SET {field} = {field} WHERE {column} = :b"),
            {"b": b},
        )
        deleted = (
            0
            if table in NO_DELETE
            else (
                await conn.execute(
                    text(f"DELETE FROM {table} WHERE {column} = :b"), {"b": b}
                )
            ).rowcount
        )
    assert (touched.rowcount, deleted) == (0, 0)
    async with engines.platform.connect() as conn:
        left = await conn.scalar(
            text(f"SELECT count(*) FROM {table} WHERE {column} = :b"), {"b": b}
        )
    assert left == seeded.counts[table][b]


@pytest.mark.asyncio
async def test_r3_an_invitation_for_another_workshop_is_rejected(
    engines: Engines, seeded: Seeded
) -> None:
    async with engines.app.begin() as conn:
        await set_workshops(conn, seeded.workshops.a)
        with pytest.raises(DBAPIError, match="row-level security policy"):
            await conn.execute(
                text(
                    "INSERT INTO invitations"
                    " (workshop_id, employee_id, email, token_hash, expires_at)"
                    " VALUES (:b, :employee_b, 'x@example.com', 'otro',"
                    " clock_timestamp() + interval '7 days')"
                ),
                {"b": seeded.workshops.b, "employee_b": seeded.workshops.admin_b},
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["b", "platform"])
async def test_r3_the_app_cannot_write_audit_entries_outside_its_workshop(
    engines: Engines, seeded: Seeded, target: str
) -> None:
    """Ni en el registro de otro taller ni en el de plataforma (workshop_id nulo):
    un fallo en /workshop no puede fabricar acciones que vea el superadministrador."""
    workshop = seeded.workshops.b if target == "b" else None
    async with engines.app.begin() as conn:
        await set_workshops(conn, seeded.workshops.a)
        with pytest.raises(DBAPIError, match="row-level security policy"):
            await conn.execute(
                text("INSERT INTO audit_log (workshop_id, action) VALUES (:w, 'x')"),
                {"w": workshop},
            )


@pytest.mark.asyncio
async def test_r3_a_row_of_a_cannot_be_moved_to_b(
    engines: Engines, seeded: Seeded
) -> None:
    """WITH CHECK también vale para UPDATE: no se puede "regalar" una fila propia
    a otro taller cambiándole el workshop_id."""
    async with engines.app.begin() as conn:
        await set_workshops(conn, seeded.workshops.a)
        with pytest.raises(DBAPIError, match="row-level security policy"):
            await conn.execute(
                text("UPDATE employees SET workshop_id = :b"),
                {"b": seeded.workshops.b},
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET action = 'otra'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ],
)
async def test_r5_the_app_role_cannot_rewrite_the_audit_log(
    engines: Engines, seeded: Seeded, statement: str
) -> None:
    """test_rls.py lo prueba con axtton_platform; aquí con axtton_app, el rol de
    todas las peticiones, y con el taller fijado (sus propias filas)."""
    async with engines.app.begin() as conn:
        await set_workshops(conn, seeded.workshops.a)
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text(statement))


@pytest.mark.asyncio
@pytest.mark.parametrize("statement", ["DELETE FROM clients", "TRUNCATE clients"])
async def test_the_app_role_cannot_delete_clients(
    engines: Engines, seeded: Seeded, statement: str
) -> None:
    """Un cliente se archiva o se anonimiza (RF-15), nunca se borra: sus órdenes y
    presupuestos tienen que seguir apuntando a su fila (migración 0004clients)."""
    async with engines.app.begin() as conn:
        await set_workshops(conn, seeded.workshops.a)
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text(statement))


@pytest.mark.asyncio
async def test_r5_the_platform_role_cannot_truncate_the_audit_log(
    engines: Engines, seeded: Seeded
) -> None:
    async with engines.platform.begin() as conn:
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text("TRUNCATE audit_log"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        (
            "INSERT INTO superadmin_invitations (email, token_hash, expires_at)"
            " VALUES ('x@example.com', 'x', clock_timestamp())"
        ),
        "UPDATE superadmin_invitations SET revoked_at = clock_timestamp()",
        "DELETE FROM superadmin_invitations",
    ],
)
async def test_the_app_role_cannot_write_superadmin_invitations(
    engines: Engines, statement: str
) -> None:
    """test_superadmins.py prueba que no puede leerla; tampoco escribirla: un
    fallo en /workshop no puede fabricarse una invitación de superadministrador."""
    async with engines.app.begin() as conn:
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text(statement))


@pytest.mark.asyncio
async def test_r7_the_application_engine_does_not_carry_the_workshop_over(
    seeded: Seeded,
) -> None:
    """R7 con el engine y la función de la propia aplicación (no uno de prueba):
    la transacción de un taller termina y la siguiente, en la misma conexión del
    pool, no ve nada."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core import db

    try:
        async with db.workshop_transaction([seeded.workshops.a]) as session:
            first_pid = await session.scalar(text("SELECT pg_backend_pid()"))
            assert await session.scalar(text("SELECT count(*) FROM employees")) == 1

        session2: AsyncSession
        async with db.SessionFactory() as session2, session2.begin():
            second_pid = await session2.scalar(text("SELECT pg_backend_pid()"))
            visible = await session2.scalar(text("SELECT count(*) FROM employees"))
            setting = await session2.scalar(
                text("SELECT current_setting('app.workshop_ids', true)")
            )
    finally:
        await db.engine.dispose()

    assert second_pid == first_pid, "la prueba necesita la misma conexión"
    assert visible == 0
    assert setting in (None, "")


def test_the_database_url_of_the_app_is_not_the_owner() -> None:
    """Si la aplicación se conectara como dueña, FORCE ROW LEVEL SECURITY seguiría
    aplicando, pero el dueño podría desactivarla (ALTER TABLE ... NO FORCE)."""
    from app.core.config import get_settings

    settings = get_settings()
    assert "axtton_app" in settings.database_url
    assert "axtton_owner" not in settings.database_url
    assert "axtton_platform" in settings.platform_database_url
    assert os.environ["MIGRATIONS_DATABASE_URL"] != settings.database_url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE workshops SET status = 'active'",
        "UPDATE workshops SET max_employees_with_access = 1000",
        "DELETE FROM workshops",
        "INSERT INTO workshops (name) VALUES ('Otro')",
        "UPDATE users SET kind = 'superadmin'",
        "DELETE FROM users",
        "UPDATE alembic_version SET version_num = 'x'",
    ],
)
async def test_the_app_cannot_change_what_belongs_to_the_platform(
    engines: Engines, seeded: Seeded, statement: str
) -> None:
    """Migración 0003grants: ni con su propio taller fijado puede axtton_app
    cambiar el estado o los límites del taller (RF-113, RF-114), convertir una
    cuenta en superadministrador ni tocar el historial de migraciones."""
    async with engines.app.begin() as conn:
        await set_workshops(conn, seeded.workshops.a)
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text(statement))
