"""La hoja de recepción firmada en la base de datos, sin pasar por el código (F6
paso 1, migración 0024receptionsheets).

Invariante 6 y RNF-11: una hoja firmada no se modifica jamás, ni desde la base de
datos. Aquí se intenta romper cada garantía con SQL y con los tres roles: la
aplicación, la plataforma y el dueño de las tablas. La única escritura que se
admite es vaciar lo personal cuando su cliente ya está anonimizado (RF-15,
RNF-40), y la firma se queda hasta su plazo (RF-56).
"""

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import Engines, TwoWorkshops
from tests.test_anonymize import ANONYMIZE_SQL
from tests.test_rls import set_workshops
from tests.test_work_orders_db import Order, seed_order

SIGNATURE = "[[[10, 20], [30, 40]]]"
SNAPSHOT = '{"odometer_km": 123456, "fuel_level": "half"}'

INSERT = (
    "INSERT INTO reception_sheets (workshop_id, work_order_id, signature_method,"
    " recorded_by_employee_id, snapshot, quote_waived, dropped_off_by_name,"
    " dropped_off_by_phone, signer_name, signature)"
    " VALUES (:w, :o, :method, :e, CAST(:snapshot AS jsonb), :waived,"
    " 'Jaime', '688', 'Jaime', CAST(:signature AS jsonb))"
)


def roles(engines: Engines) -> dict[str, AsyncEngine]:
    return {"app": engines.app, "platform": engines.platform, "owner": engines.owner}


async def run(engine: AsyncEngine, order: Order, statement: str, **params: Any) -> Any:
    """Con el taller de la orden fijado: el dueño también obedece RLS (FORCE), y
    sin taller no vería la fila y no probaría nada."""
    async with engine.begin() as conn:
        await set_workshops(conn, order.workshop_id)
        return await conn.execute(
            text(statement), {"w": order.workshop_id, "o": order.order_id, **params}
        )


async def sign(
    engine: AsyncEngine,
    order: Order,
    employee: Any,
    *,
    method: str = "screen",
    signature: str | None = SIGNATURE,
    snapshot: str = SNAPSHOT,
) -> None:
    await run(
        engine,
        order,
        INSERT,
        e=employee,
        method=method,
        snapshot=snapshot,
        waived=True,
        signature=signature,
    )


@pytest_asyncio.fixture
async def order(engines: Engines, two_workshops: TwoWorkshops) -> Order:
    return await seed_order(engines, two_workshops)


@pytest_asyncio.fixture
async def signed(engines: Engines, two_workshops: TwoWorkshops, order: Order) -> Order:
    """La orden de María con su hoja firmada en pantalla por Jaime, su hijo."""
    await sign(engines.app, order, two_workshops.admin_a)
    return order


async def sheet(engines: Engines, order: Order) -> Any:
    async with engines.platform.connect() as conn:
        return (
            await conn.execute(
                text("SELECT * FROM reception_sheets WHERE work_order_id = :o"),
                {"o": order.order_id},
            )
        ).one()


# --- Nacer firmada ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_app_stores_a_signed_sheet_and_the_server_dates_it(
    engines: Engines, two_workshops: TwoWorkshops, order: Order
) -> None:
    """La hora de la firma es la del servidor, aunque se mande otra."""
    await run(
        engines.app,
        order,
        "INSERT INTO reception_sheets (workshop_id, work_order_id, signature_method,"
        " recorded_by_employee_id, snapshot, quote_waived, signed_at)"
        " VALUES (:w, :o, 'paper', :e, '{}', false, '2001-01-01')",
        e=two_workshops.admin_a,
    )
    row = await sheet(engines, order)
    assert row.signed_at.year > 2001
    assert (row.signature_method, row.signature, row.signature_purged_at) == (
        "paper",
        None,
        None,
    )


@pytest.mark.asyncio
async def test_a_sheet_is_never_born_with_its_signature_purged(
    engines: Engines, two_workshops: TwoWorkshops, order: Order
) -> None:
    with pytest.raises(DBAPIError, match="not signed already purged"):
        await run(
            engines.platform,
            order,
            "INSERT INTO reception_sheets (workshop_id, work_order_id,"
            " signature_method, recorded_by_employee_id, snapshot, quote_waived,"
            " signature_purged_at)"
            " VALUES (:w, :o, 'screen', :e, '{}', false, clock_timestamp())",
            e=two_workshops.admin_a,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "signature", "snapshot", "constraint"),
    [
        # En papel, la firma la guarda el papel, no la base de datos.
        ("paper", SIGNATURE, SNAPSHOT, "ck_reception_sheets_signature_by_method"),
        # En pantalla, sin trazos no hay firma.
        ("screen", None, SNAPSHOT, "ck_reception_sheets_signature_by_method"),
        # Ni otro método: lo paran sus dos CHECK, y Postgres nombra uno.
        ("pen", None, SNAPSHOT, "ck_reception_sheets_signature_(by_)?method"),
        ("paper", None, "[1, 2]", "ck_reception_sheets_snapshot_object"),
    ],
)
async def test_the_database_refuses_an_inconsistent_sheet(
    engines: Engines,
    two_workshops: TwoWorkshops,
    order: Order,
    method: str,
    signature: str | None,
    snapshot: str,
    constraint: str,
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        await sign(
            engines.app,
            order,
            two_workshops.admin_a,
            method=method,
            signature=signature,
            snapshot=snapshot,
        )


@pytest.mark.asyncio
async def test_an_order_has_one_signed_sheet(
    engines: Engines, two_workshops: TwoWorkshops, signed: Order
) -> None:
    """Firmar dos veces la misma orden choca con el índice único (RF-52)."""
    with pytest.raises(IntegrityError, match="uq_reception_sheets_work_order_id"):
        await sign(
            engines.platform,
            signed,
            two_workshops.admin_a,
            method="paper",
            signature=None,
        )


@pytest.mark.asyncio
async def test_a_sheet_of_another_workshop_cannot_be_stored(
    engines: Engines, two_workshops: TwoWorkshops, order: Order
) -> None:
    """Desde B, con la orden de A: RLS (WITH CHECK) la para."""
    async with engines.app.begin() as conn:
        await set_workshops(conn, two_workshops.b)
        with pytest.raises(DBAPIError, match="row-level security policy"):
            await conn.execute(
                text(
                    "INSERT INTO reception_sheets (workshop_id, work_order_id,"
                    " signature_method, recorded_by_employee_id, snapshot,"
                    " quote_waived) VALUES (:w, :o, 'paper', :e, '{}', false)"
                ),
                {
                    "w": order.workshop_id,
                    "o": order.order_id,
                    "e": two_workshops.admin_a,
                },
            )


# --- Congelada (invariante 6) ----------------------------------------------------

CHANGES = [
    "UPDATE reception_sheets SET snapshot = '{\"odometer_km\": 1}'",
    "UPDATE reception_sheets SET quote_waived = false",
    "UPDATE reception_sheets SET signed_at = signed_at - interval '1 day'",
    "UPDATE reception_sheets SET signature = '[[[0, 0], [1, 1]]]'",
    "UPDATE reception_sheets SET signature_method = 'paper', signature = NULL",
    "UPDATE reception_sheets SET signature = NULL, signature_purged_at = now()",
    "UPDATE reception_sheets SET signer_name = 'Otro'",
    "UPDATE reception_sheets SET dropped_off_by_phone = '699'",
    "UPDATE reception_sheets SET created_at = created_at",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform", "owner"])
@pytest.mark.parametrize("statement", CHANGES)
async def test_a_signed_sheet_does_not_change_with_any_role(
    engines: Engines, signed: Order, role: str, statement: str
) -> None:
    """A la aplicación la para antes el permiso por columna, salvo en lo
    personal; a la plataforma y al dueño, el trigger."""
    before = await sheet(engines, signed)
    with pytest.raises(DBAPIError, match="cannot change|permission denied"):
        await run(roles(engines)[role], signed, f"{statement} WHERE work_order_id = :o")
    assert await sheet(engines, signed) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform", "owner"])
async def test_nobody_deletes_a_signed_sheet(
    engines: Engines, signed: Order, role: str
) -> None:
    with pytest.raises(DBAPIError, match="cannot change|permission denied"):
        await run(
            roles(engines)[role],
            signed,
            "DELETE FROM reception_sheets WHERE work_order_id = :o",
        )
    assert await sheet(engines, signed) is not None


# --- Lo personal, al anonimizar (RF-15, RNF-40) -----------------------------------

ERASE = (
    "UPDATE reception_sheets SET dropped_off_by_name = NULL,"
    " dropped_off_by_phone = NULL, signer_name = NULL WHERE work_order_id = :o"
)


async def anonymize_maria(engines: Engines, order: Order) -> None:
    async with engines.platform.begin() as conn:
        await conn.execute(text(ANONYMIZE_SQL), {"w": order.workshop_id})


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform", "owner"])
async def test_the_personal_data_stays_while_the_client_is_not_anonymized(
    engines: Engines, signed: Order, role: str
) -> None:
    with pytest.raises(DBAPIError, match="cannot change"):
        await run(roles(engines)[role], signed, ERASE)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform", "owner"])
async def test_once_anonymized_only_the_personal_data_is_erased(
    engines: Engines, signed: Order, role: str
) -> None:
    """Lo demás de la hoja, y la firma, se quedan (RF-56)."""
    before = await sheet(engines, signed)
    await anonymize_maria(engines, signed)
    await run(roles(engines)[role], signed, ERASE)
    after = await sheet(engines, signed)
    assert (
        after.dropped_off_by_name,
        after.dropped_off_by_phone,
        after.signer_name,
    ) == (
        None,
        None,
        None,
    )
    assert (after.snapshot, after.signature, after.signed_at, after.quote_waived) == (
        before.snapshot,
        before.signature,
        before.signed_at,
        before.quote_waived,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        # A medias no: o todo lo personal, o nada.
        "UPDATE reception_sheets SET signer_name = NULL",
        # Ni de paso con otra cosa.
        (
            "UPDATE reception_sheets SET dropped_off_by_name = NULL,"
            " dropped_off_by_phone = NULL, signer_name = NULL, signature = NULL,"
            " signature_purged_at = now()"
        ),
        (
            "UPDATE reception_sheets SET dropped_off_by_name = NULL,"
            " dropped_off_by_phone = NULL, signer_name = NULL, quote_waived = false"
        ),
    ],
)
async def test_anonymizing_erases_nothing_else(
    engines: Engines, signed: Order, statement: str
) -> None:
    await anonymize_maria(engines, signed)
    with pytest.raises(DBAPIError, match="cannot change"):
        await run(engines.platform, signed, f"{statement} WHERE work_order_id = :o")
