"""Pruebas adversas del cierre de F2 que faltaban (arquitectura §2, §4 y §10).

- R3 tabla a tabla: test_rls_tables.py solo prueba el INSERT con el taller de B
  en `invitations` y `audit_log`, y mover una fila a B solo en `employees`.
- La matriz de permisos (especificación §3) recorrida en TODAS las rutas de
  /workshop con una sesión de mecánico: T2 comprueba el actor, no el rol.
- Un barrido de /workshop con un administrador de un taller real: el de
  test_adverse_f1.py usa un taller inventado, así que todo para en la
  dependencia (404) y nunca llega a los endpoints.
- Carreras que no tenían prueba: los límites de vehículos y de órdenes, el
  cobro, anonimizar frente a darle un vehículo y el reenvío de un trabajo.
- El invariante 7 en la base de datos.
"""

import asyncio
import json
import re
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.infra.email import InMemoryEmailSender
from tests.conftest import Engines, TwoWorkshops
from tests.test_clients import open_workshop
from tests.test_concurrency import (
    GRACE,
    MakeAccount,
    dispose_global_engines,
    finish,
    open_order,
    open_transaction,
    order_in,
    shop_with_a_car,
)
from tests.test_employees import AdminSession, add_mechanic, invite_and_accept
from tests.test_rls import set_workshops
from tests.test_rls_tables import WORKSHOP_TABLES, Seeded, seeded
from tests.test_work_orders import outbox

__all__ = ["dispose_global_engines", "outbox", "seeded"]

WORKSHOP_PREFIX = "/api/v1/workshop"

# --- R3 tabla a tabla --------------------------------------------------------

# `workshops` no: axtton_app no tiene INSERT ni UPDATE sobre ella
# (test_the_app_cannot_change_what_belongs_to_the_platform). `audit_log` e
# `invitations` ya tienen su R3 en test_rls_tables.py.
R3_TABLES = sorted(set(WORKSHOP_TABLES) - {"workshops", "audit_log", "invitations"})
BLOCKED_FIRST_BY = {"work_order_counters": "work order counters only grow"}
# Al insertar, el trigger BEFORE de las líneas y de las decisiones busca su
# versión antes de que WITH CHECK mire la fila, y desde A la de B no existe (RLS
# la oculta): la para él, por el mismo aislamiento (0013quotes).
INSERT_BLOCKED_FIRST_BY = {
    "quote_lines": r"quote \S+ not found",
    "quote_decisions": r"quote \S+ not found",
}


async def insertable_copy_of_b(
    engines: Engines, table: str, b: UUID
) -> tuple[list[str], dict[str, Any]]:
    """Una fila de B tal cual, con las columnas que axtton_app puede insertar y
    un id nuevo: lo único que la hace inaceptable desde A es su workshop_id."""
    async with engines.platform.connect() as conn:
        columns = (
            await conn.scalars(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_schema = 'public' AND table_name = :t"
                    " AND is_generated = 'NEVER' AND is_identity = 'NO'"
                    " AND has_column_privilege('axtton_app', :t, column_name,"
                    " 'INSERT')"
                    " ORDER BY ordinal_position"
                ),
                {"t": table},
            )
        ).all()
        row = (
            (
                await conn.execute(
                    text(f"SELECT * FROM {table} WHERE workshop_id = :b LIMIT 1"),
                    {"b": b},
                )
            )
            .mappings()
            .one()
        )
    values = {column: row[column] for column in columns}
    # Un jsonb (el desglose de IVA de un presupuesto) vuelve como lista o
    # diccionario de Python: se manda otra vez como texto JSON.
    for column, value in values.items():
        if isinstance(value, list | dict):
            values[column] = json.dumps(value)
    if "id" in values:
        values["id"] = uuid4()
    return list(columns), values


@pytest.mark.asyncio
@pytest.mark.parametrize("table", R3_TABLES)
async def test_r3_from_a_no_table_accepts_a_row_of_b(
    engines: Engines, seeded: Seeded, table: str
) -> None:
    """R3: fijado A, un INSERT con el workshop_id de B lo rechaza WITH CHECK,
    aunque la fila (sus FK, sus datos) sea por lo demás válida en B."""
    a, b = seeded.workshops.a, seeded.workshops.b
    columns, values = await insertable_copy_of_b(engines, table, b)
    assert "workshop_id" in columns, "prueba de control: se inserta con el taller"
    statement = text(
        f"INSERT INTO {table} ({', '.join(columns)})"
        f" VALUES ({', '.join(':' + c for c in columns)})"
    )
    async with engines.app.begin() as conn:
        await set_workshops(conn, a)
        expected = INSERT_BLOCKED_FIRST_BY.get(table, "row-level security policy")
        with pytest.raises(DBAPIError, match=expected):
            await conn.execute(statement, values)


@pytest.mark.asyncio
@pytest.mark.parametrize("table", R3_TABLES)
async def test_r3_from_a_no_row_can_be_moved_to_b(
    engines: Engines, seeded: Seeded, table: str
) -> None:
    """WITH CHECK también en UPDATE, en cada tabla: no se regala una fila propia
    a otro taller. Donde axtton_app ni siquiera puede escribir workshop_id, lo
    para antes el permiso."""
    a, b = seeded.workshops.a, seeded.workshops.b
    async with engines.platform.connect() as conn:
        updatable = await conn.scalar(
            text(
                "SELECT has_column_privilege('axtton_app', :t, 'workshop_id', 'UPDATE')"
            ),
            {"t": table},
        )
    expected = "row-level security policy" if updatable else "permission denied"
    # El trigger BEFORE de los contadores (cambiar de taller o de año no es
    # "crecer") corre antes que WITH CHECK: lo para él, y RLS ni llega a mirarlo.
    expected = BLOCKED_FIRST_BY.get(table, expected)
    async with engines.app.begin() as conn:
        await set_workshops(conn, a)
        with pytest.raises(DBAPIError, match=expected):
            await conn.execute(
                text(f"UPDATE {table} SET workshop_id = :b WHERE workshop_id = :a"),
                {"a": a, "b": b},
            )


# --- Invariante 7 en la base de datos ----------------------------------------


# Hallazgo del cierre de F2: axtton_app tenía UPDATE sobre todas las columnas, y
# el invariante 7 (y el acceso del portal, que irá por work_orders.client_id) lo
# protegía solo el código. La migración 0011ordercols limita las columnas.
@pytest.mark.asyncio
@pytest.mark.parametrize("column", ["client_id", "vehicle_id", "number", "year"])
async def test_the_client_and_vehicle_of_an_order_cannot_change_after_opening(
    engines: Engines, seeded: Seeded, column: str
) -> None:
    a = seeded.workshops.a
    async with engines.platform.begin() as conn:
        other_client = await conn.scalar(
            text(
                "INSERT INTO clients (workshop_id, name, phone)"
                " VALUES (:w, 'Otro', '611') RETURNING id"
            ),
            {"w": a},
        )
        other_vehicle = await conn.scalar(
            text(
                "INSERT INTO vehicles (workshop_id, plate, plate_normalized)"
                " VALUES (:w, '9999 ZZZ', '9999ZZZ') RETURNING id"
            ),
            {"w": a},
        )
    target = {
        "client_id": other_client,
        "vehicle_id": other_vehicle,
        "number": 999,
        "year": 2099,
    }[column]
    async with engines.app.begin() as conn:
        await set_workshops(conn, a)
        with pytest.raises(DBAPIError):
            await conn.execute(
                text(f"UPDATE work_orders SET {column} = :x WHERE workshop_id = :a"),
                {"x": target, "a": a},
            )


# --- La matriz de permisos en todas las rutas del taller ---------------------

# (método, plantilla de la ruta sin el prefijo) que el mecánico SÍ puede pedir
# (especificación §3): ver clientes, vehículos y órdenes, mover los estados de
# reparación, escribir el diagnóstico, las notas y los trabajos, y su cuenta.
MECHANIC_ALLOWED = {
    ("GET", "/staff"),
    ("GET", "/clients"),
    ("GET", "/clients/{client_id}"),
    ("GET", "/search"),
    ("GET", "/vehicles"),
    ("GET", "/vehicles/suggestions"),
    ("GET", "/vehicles/{vehicle_id}"),
    ("GET", "/orders"),
    ("GET", "/orders/unpaid"),
    ("GET", "/orders/{order_id}"),
    ("POST", "/orders/{order_id}/status"),
    ("GET", "/orders/{order_id}/worklog"),
    ("POST", "/orders/{order_id}/diagnosis"),
    ("POST", "/orders/{order_id}/notes"),
    ("POST", "/orders/{order_id}/work-entries"),
    ("POST", "/orders/{order_id}/work-entries/{entry_id}/void"),
    # Ver los presupuestos (F3), sin importes si el taller lo desactiva.
    ("GET", "/orders/{order_id}/quotes"),
    ("POST", "/account/password"),
    ("GET", "/account/sessions"),
    ("POST", "/account/sessions/revoke-others"),
    ("GET", "/me"),
    ("GET", "/active"),
}
# Lo que es solo del administrador: empleados, límites, auditoría, crear y
# editar clientes y vehículos, el titular, anonimizar, abrir y editar órdenes,
# deshacer, "sin presupuesto" y el cobro.
ADMIN_ONLY = {
    ("GET", "/employees"),
    ("POST", "/employees"),
    ("PATCH", "/employees/{employee_id}"),
    ("POST", "/employees/{employee_id}/access/remove"),
    ("POST", "/employees/{employee_id}/invitation"),
    ("GET", "/limits"),
    ("GET", "/audit"),
    ("POST", "/clients"),
    ("PATCH", "/clients/{client_id}"),
    ("POST", "/clients/{client_id}/archive"),
    ("POST", "/clients/{client_id}/unarchive"),
    ("POST", "/clients/{client_id}/anonymize"),
    ("POST", "/vehicles"),
    ("PATCH", "/vehicles/{vehicle_id}"),
    ("POST", "/vehicles/{vehicle_id}/owner"),
    ("POST", "/orders"),
    ("PATCH", "/orders/{order_id}"),
    ("POST", "/orders/{order_id}/undo"),
    ("POST", "/orders/{order_id}/no-quote"),
    ("PUT", "/orders/{order_id}/payment"),
    # Configuración del taller (F3 paso 1, RF-02).
    ("GET", "/settings"),
    ("PATCH", "/settings"),
    ("PUT", "/settings/logo"),
    ("GET", "/settings/logo"),
    ("DELETE", "/settings/logo"),
    ("GET", "/labor-rates"),
    ("POST", "/labor-rates"),
    ("PATCH", "/labor-rates/{rate_id}"),
    ("POST", "/labor-rates/{rate_id}/archive"),
    ("POST", "/labor-rates/{rate_id}/unarchive"),
    # Preparar presupuestos (F3 paso 4).
    ("POST", "/orders/{order_id}/quotes"),
    ("PUT", "/quotes/{quote_id}"),
    ("POST", "/quotes/{quote_id}/discard"),
}


def workshop_operations() -> set[tuple[str, str]]:
    from app.main import app

    return {
        (method.upper(), path.removeprefix(WORKSHOP_PREFIX))
        for path, operations in app.openapi()["paths"].items()
        if path.startswith(WORKSHOP_PREFIX + "/")
        for method in operations
    }


def concrete(template: str) -> str:
    return WORKSHOP_PREFIX + re.sub(r"\{[^}]+\}", str(uuid4()), template)


def test_every_workshop_route_is_classified_for_the_mechanic() -> None:
    """Prueba de control: una ruta nueva de /workshop obliga a decidir aquí si el
    mecánico puede pedirla. Sin esto, la prueba de abajo no la miraría."""
    assert not MECHANIC_ALLOWED & ADMIN_ONLY
    assert workshop_operations() == MECHANIC_ALLOWED | ADMIN_ONLY


@pytest_asyncio.fixture
async def workshop_admin(client: AsyncClient) -> AdminSession:
    from app.scripts.reset_data import truncate_all

    await truncate_all()
    return await open_workshop(client, "Talleres Pérez")


@pytest.mark.asyncio
async def test_a_mechanic_is_refused_every_admin_route_and_only_those(
    client: AsyncClient,
    workshop_admin: AdminSession,
    outbox: InMemoryEmailSender,
) -> None:
    """RNF-03 en todas las rutas: con ids inventados y sin cuerpo, una ruta del
    administrador responde 403 `not_allowed` al mecánico ANTES de mirar nada
    más; una que sí puede pedir nunca le responde 403."""
    mechanic = await invite_and_accept(
        client, workshop_admin, outbox, await add_mechanic(client, workshop_admin)
    )
    wrong: list[tuple[str, str, int, str]] = []
    for method, template in sorted(workshop_operations()):
        response = await client.request(
            method,
            concrete(template),
            headers=mechanic,
            json={} if method != "GET" else None,
        )
        refused = (
            response.status_code == 403 and response.json().get("code") == "not_allowed"
        )
        if refused != ((method, template) in ADMIN_ONLY):
            wrong.append((method, template, response.status_code, response.text))
    assert wrong == []


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"version": 1}])
async def test_no_workshop_route_answers_a_real_admin_with_a_server_error(
    client: AsyncClient, workshop_admin: AdminSession, body: dict[str, int]
) -> None:
    """Como el barrido de test_adverse_f1.py, pero dentro de un taller real: ahí
    la dependencia ya da 404 por el taller inventado y ningún endpoint llega a
    ejecutarse. Aquí sí llegan, con ids que no existen y un cuerpo vacío o con
    solo la versión: todo debe ser un error del cliente, nunca un 500."""
    errors: list[tuple[str, str, int, str]] = []
    checked = 0
    for method, template in sorted(workshop_operations()):
        if template == "/account/sessions/revoke-others":
            continue  # cerraría la propia sesión de la prueba en otras peticiones
        checked += 1
        response = await client.request(
            method,
            concrete(template),
            headers=workshop_admin.headers,
            json=body if method != "GET" else None,
        )
        if response.status_code >= 500:
            errors.append((method, template, response.status_code, response.text))
    assert checked >= 30  # prueba de control
    assert errors == []


# --- Carreras que faltaban ---------------------------------------------------


async def set_limit(
    engines: Engines, workshop_id: UUID, column: str, value: int
) -> None:
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(f"UPDATE workshops SET {column} = :v WHERE id = :w"),
            {"v": value, "w": workshop_id},
        )


async def count(engines: Engines, sql: str, **params: Any) -> int:
    async with engines.platform.connect() as conn:
        value: int = await conn.scalar(text(sql), params)
    return value


@pytest.mark.asyncio
async def test_two_orders_at_once_with_one_free_slot_this_month_leave_one_out(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """§10, RF-114: con un hueco de órdenes este mes, dos aperturas a la vez
    contarían cada una sin ver la otra y entrarían las dos. ensure_room las pone
    en fila: la segunda cuenta después de la primera y no cabe.

    Comprobado que falla sin la guarda (repositories/limits.py::lock como no-op):
    entran las dos."""
    a = two_workshops.a
    ana, _, _, car = await shop_with_a_car(engines, make_account, a)
    await set_limit(engines, a, "max_orders_per_month", 1)

    async with open_transaction(a) as first, open_transaction(a) as second:
        await open_order(first, a, ana, car)
        work = asyncio.create_task(open_order(second, a, ana, car))
        await asyncio.sleep(GRACE)
        assert not work.done(), "la segunda debería esperar al recuento"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    assert outcome.code == "order_limit_reached"
    assert await count(engines, "SELECT count(*) FROM work_orders") == 1


@pytest.mark.asyncio
async def test_two_vehicles_at_once_with_one_free_slot_leave_one_out(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """Lo mismo con los vehículos. Comprobado que falla sin la guarda."""
    from app.services import vehicles as vehicle_service

    a = two_workshops.a
    _, maria, _, _ = await shop_with_a_car(engines, make_account, a)
    await set_limit(engines, a, "max_vehicles", 2)

    async def add(session: AsyncSession, plate: str) -> UUID:
        return await vehicle_service.create_vehicle(session, a, {"plate": plate}, maria)

    async with open_transaction(a) as first, open_transaction(a) as second:
        await add(first, "1111 BBB")
        work = asyncio.create_task(add(second, "2222 CCC"))
        await asyncio.sleep(GRACE)
        assert not work.done(), "la segunda debería esperar al recuento"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    assert outcome.code == "vehicle_limit_reached"
    assert await count(engines, "SELECT count(*) FROM vehicles") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("second_one", ["give", "create"])
async def test_a_client_being_anonymized_does_not_receive_a_vehicle(
    engines: Engines,
    two_workshops: TwoWorkshops,
    make_account: MakeAccount,
    second_one: str,
) -> None:
    """RF-15 y RF-12: Ana anonimiza a Luis (sin confirmar) mientras otro le pasa
    el coche de María o le da de alta uno nuevo. Sin esperar, leería a Luis aún
    con nombre y el coche acabaría con un titular actual anonimizado, algo que
    la API no deja hacer a nadie (`client_anonymized`). `_new_owner` pide el
    bloqueo compartido del cliente y anonimizar el exclusivo: la segunda espera
    y lo ve anonimizado. (Al revés no hay carrera: anonimizar a un titular es
    legítimo, RF-15.) Comprobado que falla sin el bloqueo compartido."""
    from app.services import clients as client_service
    from app.services import vehicles as vehicle_service

    a = two_workshops.a
    ana, _, luis, car = await shop_with_a_car(engines, make_account, a)

    async def give(session: AsyncSession) -> None:
        await vehicle_service.change_owner(
            session, a, ana.user_id, car, expected_version=1, client_id=luis
        )

    async def create(session: AsyncSession) -> None:
        await vehicle_service.create_vehicle(session, a, {"plate": "5555 DDD"}, luis)

    steps = {"give": give, "create": create}
    async with open_transaction(a) as first, open_transaction(a) as second:
        await client_service.anonymize_client(
            first, a, ana.user_id, luis, expected_version=1
        )
        work = asyncio.create_task(steps[second_one](second))
        await asyncio.sleep(GRACE)
        assert not work.done(), "la segunda debería esperar al cliente"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    assert outcome.code == "client_anonymized"
    assert (
        await count(
            engines,
            "SELECT count(*) FROM vehicle_ownerships"
            " WHERE client_id = :l AND ended_at IS NULL",
            l=luis,
        )
        == 0
    )


async def one_row(engines: Engines, sql: str, **params: Any) -> tuple[Any, ...]:
    async with engines.platform.connect() as conn:
        return tuple((await conn.execute(text(sql), params)).one())


@pytest.mark.asyncio
async def test_the_same_work_entry_sent_twice_at_once_is_saved_once(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """RNF-22, como la nota de test_concurrency.py pero con un trabajo: el
    reenvío llega mientras el primero, que sí llegó, no ha confirmado. El
    segundo espera a la orden (FOR NO KEY UPDATE) y luego choca con la clave
    primaria: 409 `already_saved`, un solo trabajo y no un 500."""
    from app.services import worklog as worklog_service

    a = two_workshops.a
    ana, order_id = await order_in(engines, make_account, a, [])
    entry_id = uuid4()

    async def send(session: AsyncSession) -> UUID:
        return await worklog_service.add_work_entry(
            session,
            a,
            ana.employee_id,
            order_id,
            entry_id=entry_id,
            employee_id=ana.employee_id,
            description="Pastillas",
            worked_on=date(2026, 10, 26),
            hours=None,
        )

    async with open_transaction(a) as first, open_transaction(a) as second:
        await send(first)
        work = asyncio.create_task(send(second))
        await asyncio.sleep(GRACE)
        assert not work.done(), "el reenvío debería esperar al primero"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    assert outcome.code == "already_saved"
    assert (
        await count(
            engines, "SELECT count(*) FROM work_entries WHERE id = :e", e=entry_id
        )
        == 1
    )


@pytest.mark.asyncio
async def test_two_payments_at_once_from_the_same_version_record_one(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """RF-28: dos personas registran a la vez el cobro desde la misma versión
    (una en efectivo, otra con tarjeta). La segunda espera a la orden bloqueada
    y recibe un 409: queda un cobro y una sola entrada en la auditoría."""
    from app.services import work_orders as order_service

    a = two_workshops.a
    ana, order_id = await order_in(engines, make_account, a, [])
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO work_order_status_changes"
                " (workshop_id, work_order_id, from_status, to_status, cause)"
                " SELECT workshop_id, id, status, 'delivered', 'manual'"
                " FROM work_orders WHERE id = :o"
            ),
            {"o": order_id},
        )
        version = await conn.scalar(
            text(
                "UPDATE work_orders SET status = 'delivered',"
                " delivered_at = clock_timestamp() WHERE id = :o RETURNING version"
            ),
            {"o": order_id},
        )

    async def pay(session: AsyncSession, method: str) -> None:
        await order_service.record_payment(
            session,
            a,
            ana.user_id,
            order_id,
            expected_version=version,
            status="paid",
            method=method,
            amount_cents=12000,
            paid_on=date(2026, 10, 1),
        )

    async with open_transaction(a) as first, open_transaction(a) as second:
        await pay(first, "cash")
        work = asyncio.create_task(pay(second, "card"))
        await asyncio.sleep(GRACE)
        assert not work.done(), "el segundo cobro debería esperar a la orden"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    assert outcome.code == "modified_by_someone_else"
    method, audited = await one_row(
        engines,
        "SELECT payment_method, (SELECT count(*) FROM audit_log"
        " WHERE action = 'payment_recorded' AND target_id = :o)"
        " FROM work_orders WHERE id = :o",
        o=order_id,
    )
    assert (method, audited) == ("cash", 1)
