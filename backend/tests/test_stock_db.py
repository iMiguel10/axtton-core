"""El libro de stock en la base de datos, sin pasar por el código (F7 paso 2,
migración 0028stockmovements).

RNF-12 lo garantiza la base de datos: un movimiento no se cambia ni se borra con
ningún rol. A la aplicación y a la plataforma las para el permiso; al dueño de
las tablas, el trigger `stock_movements_frozen`. Y una anulación es
exactamente la contraria de su original (`stock_movements_reversal_matches`).
"""

from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import Engines, TwoWorkshops
from tests.test_rls import set_workshops

INSERT = (
    "INSERT INTO stock_movements (workshop_id, part_id, kind, quantity,"
    " unit_cost_cents, note, reverses_id, employee_id)"
    " VALUES (:w, :p, :kind, :quantity, :cost, :note, :reverses, :e) RETURNING id"
)


def roles(engines: Engines) -> dict[str, AsyncEngine]:
    return {"app": engines.app, "platform": engines.platform, "owner": engines.owner}


async def run(
    engine: AsyncEngine, workshop: UUID, statement: str, **params: Any
) -> Any:
    """Con el taller fijado: el dueño también obedece RLS (FORCE), y sin taller
    no vería la fila y no probaría nada."""
    async with engine.begin() as conn:
        await set_workshops(conn, workshop)
        return (await conn.execute(text(statement), params)).scalar()


async def insert(
    engines: Engines,
    two_workshops: TwoWorkshops,
    part: UUID,
    kind: str,
    quantity: str,
    *,
    cost: int | None = None,
    note: str | None = None,
    reverses: UUID | None = None,
    workshop: UUID | None = None,
) -> UUID:
    movement: UUID = await run(
        engines.app,
        workshop or two_workshops.a,
        INSERT,
        w=two_workshops.a,
        p=part,
        kind=kind,
        quantity=quantity,
        cost=cost,
        note=note,
        reverses=reverses,
        e=two_workshops.admin_a,
    )
    return movement


async def seed_part(engines: Engines, workshop: UUID, reference: str = "BAT") -> UUID:
    async with engines.platform.begin() as conn:
        part: UUID = await conn.scalar(
            text(
                "INSERT INTO parts (workshop_id, reference, description,"
                " sale_price_cents, vat_bp) VALUES (:w, :r, 'Batería', 9500, 2100)"
                " RETURNING id"
            ),
            {"w": workshop, "r": reference},
        )
    return part


@pytest_asyncio.fixture
async def part(engines: Engines, two_workshops: TwoWorkshops) -> UUID:
    return await seed_part(engines, two_workshops.a)


@pytest_asyncio.fixture
async def entry(engines: Engines, two_workshops: TwoWorkshops, part: UUID) -> UUID:
    return await insert(engines, two_workshops, part, "in", "5", cost=6000)


async def ledger(engines: Engines) -> list[tuple[Any, ...]]:
    async with engines.platform.connect() as conn:
        rows = await conn.execute(text("SELECT * FROM stock_movements ORDER BY seq"))
        return [tuple(row) for row in rows]


# --- Append-only con cualquier rol (RNF-12) ----------------------------------

CHANGES = [
    "UPDATE stock_movements SET quantity = 50",
    "UPDATE stock_movements SET unit_cost_cents = 1",
    "UPDATE stock_movements SET note = 'otra'",
    "UPDATE stock_movements SET created_at = created_at - interval '1 day'",
    "UPDATE stock_movements SET created_at = created_at",
    "DELETE FROM stock_movements",
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "stopped_by"),
    [
        ("app", "permission denied"),
        ("platform", "permission denied"),
        ("owner", "cannot change: it is a ledger"),
    ],
)
@pytest.mark.parametrize("statement", CHANGES)
async def test_a_movement_never_changes_nor_goes_with_any_role(
    engines: Engines,
    two_workshops: TwoWorkshops,
    entry: UUID,
    role: str,
    stopped_by: str,
    statement: str,
) -> None:
    """A la aplicación y a la plataforma las para el permiso; al dueño, que lo
    tiene todo, el trigger. Cada uno con su mensaje: si faltara el trigger, el
    dueño podría y la prueba lo diría."""
    before = await ledger(engines)
    with pytest.raises(DBAPIError, match=stopped_by):
        await run(roles(engines)[role], two_workshops.a, statement)
    assert await ledger(engines) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform"])
async def test_the_app_and_the_platform_cannot_truncate_the_ledger(
    engines: Engines, two_workshops: TwoWorkshops, entry: UUID, role: str
) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        await run(roles(engines)[role], two_workshops.a, "TRUNCATE stock_movements")


# --- Lo que admite el libro ----------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "quantity", "cost", "note"),
    [
        ("in", "-1", 100, None),  # una entrada nunca resta
        ("in", "1", None, None),  # una entrada lleva su coste (RF-91)
        ("out", "1", None, None),  # una salida nunca suma
        ("out", "-1", 100, None),  # el coste es de las entradas
        ("adjustment", "1", None, None),  # un ajuste lleva su motivo (RF-92)
        ("adjustment", "1", None, "  "),
        ("adjustment", "0", None, "nada"),  # 0 no mueve nada
        ("other", "1", None, "x"),
    ],
)
async def test_the_database_refuses_an_inconsistent_movement(
    engines: Engines,
    two_workshops: TwoWorkshops,
    part: UUID,
    kind: str,
    quantity: str,
    cost: int | None,
    note: str | None,
) -> None:
    with pytest.raises(IntegrityError, match="check constraint"):
        await insert(engines, two_workshops, part, kind, quantity, cost=cost, note=note)


@pytest.mark.asyncio
async def test_a_movement_of_another_workshop_cannot_be_stored(
    engines: Engines, two_workshops: TwoWorkshops, part: UUID
) -> None:
    """Desde B, con la pieza de A: RLS (WITH CHECK) la para."""
    with pytest.raises(DBAPIError, match="row-level security policy"):
        await insert(
            engines,
            two_workshops,
            part,
            "in",
            "1",
            cost=1,
            workshop=two_workshops.b,
        )


# --- Anulaciones -------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_reversal_undoes_exactly_its_movement(
    engines: Engines, two_workshops: TwoWorkshops, part: UUID, entry: UUID
) -> None:
    other = await seed_part(engines, two_workshops.a, "OTRA")
    for target, quantity in ((part, "-4"), (part, "5"), (other, "-5")):
        with pytest.raises(DBAPIError, match="must undo exactly its movement"):
            await insert(
                engines,
                two_workshops,
                target,
                "reversal",
                quantity,
                note="error",
                reverses=entry,
            )
    reversal = await insert(
        engines, two_workshops, part, "reversal", "-5", note="error", reverses=entry
    )
    # Una anulación no se anula.
    with pytest.raises(DBAPIError, match="a reversal cannot be reversed"):
        await insert(
            engines,
            two_workshops,
            part,
            "reversal",
            "5",
            note="error",
            reverses=reversal,
        )


@pytest.mark.asyncio
async def test_a_movement_is_reversed_only_once(
    engines: Engines, two_workshops: TwoWorkshops, part: UUID, entry: UUID
) -> None:
    await insert(
        engines, two_workshops, part, "reversal", "-5", note="error", reverses=entry
    )
    with pytest.raises(IntegrityError, match="uq_stock_movements_reverses_id"):
        await insert(
            engines,
            two_workshops,
            part,
            "reversal",
            "-5",
            note="otra vez",
            reverses=entry,
        )


@pytest.mark.asyncio
async def test_a_reversal_needs_its_original_and_its_reason(
    engines: Engines, two_workshops: TwoWorkshops, part: UUID, entry: UUID
) -> None:
    with pytest.raises(IntegrityError, match="check constraint"):
        await insert(engines, two_workshops, part, "reversal", "-5", reverses=entry)
    # Sin original, la para antes el trigger, que corre antes que los CHECK.
    with pytest.raises(IntegrityError, match="not found"):
        await insert(
            engines, two_workshops, part, "reversal", "-5", note="sin original"
        )


@pytest.mark.asyncio
async def test_a_reversal_cannot_reach_a_movement_of_another_workshop(
    engines: Engines, two_workshops: TwoWorkshops, entry: UUID
) -> None:
    """La pieza de B, anulando la entrada de A: bajo RLS, el trigger no ve el
    original y la para antes que la FK compuesta."""
    theirs = await seed_part(engines, two_workshops.b)
    with pytest.raises(DBAPIError, match="not found"):
        await run(
            engines.app,
            two_workshops.b,
            INSERT,
            w=two_workshops.b,
            p=theirs,
            kind="reversal",
            quantity="-5",
            cost=None,
            note="robo",
            reverses=entry,
            e=two_workshops.admin_b,
        )
