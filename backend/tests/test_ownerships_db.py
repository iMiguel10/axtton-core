"""La titularidad en la base de datos, sin pasar por el código (arquitectura §3).

Que nunca haya dos titulares a la vez y que un periodo cerrado no cambie no
depende de que el service lo haga bien: lo impiden el índice parcial, la
restricción EXCLUDE, el trigger y los permisos de axtton_app. Aquí se intenta
romper cada uno directamente con SQL.
"""

from dataclasses import dataclass
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import Engines, TwoWorkshops
from tests.test_rls import set_workshops


@dataclass(frozen=True)
class Car:
    workshop_id: UUID
    vehicle_id: UUID
    maria: UUID
    luis: UUID
    # El periodo abierto de María, que empezó hace un año.
    period_id: UUID


@pytest_asyncio.fixture
async def car(engines: Engines, two_workshops: TwoWorkshops) -> Car:
    a = two_workshops.a
    async with engines.platform.begin() as conn:
        maria, luis = [
            await conn.scalar(
                text(
                    "INSERT INTO clients (workshop_id, name, phone)"
                    " VALUES (:w, :n, '600') RETURNING id"
                ),
                {"w": a, "n": name},
            )
            for name in ("María", "Luis")
        ]
        vehicle = await conn.scalar(
            text(
                "INSERT INTO vehicles (workshop_id, plate, plate_normalized)"
                " VALUES (:w, '1234 BCD', '1234BCD') RETURNING id"
            ),
            {"w": a},
        )
        period = await conn.scalar(
            text(
                "INSERT INTO vehicle_ownerships"
                " (workshop_id, vehicle_id, client_id, started_at)"
                " VALUES (:w, :v, :c, clock_timestamp() - interval '1 year')"
                " RETURNING id"
            ),
            {"w": a, "v": vehicle, "c": maria},
        )
    return Car(a, vehicle, maria, luis, period)


async def insert_period(
    engines: Engines, car: Car, client: UUID, started: str, ended: str | None
) -> None:
    """Con el rol de plataforma (se salta RLS, no las restricciones)."""
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO vehicle_ownerships"
                " (workshop_id, vehicle_id, client_id, started_at, ended_at)"
                f" VALUES (:w, :v, :c, {started}, {ended or 'NULL'})"
            ),
            {"w": car.workshop_id, "v": car.vehicle_id, "c": client},
        )


@pytest.mark.asyncio
async def test_a_vehicle_cannot_have_two_current_owners(
    engines: Engines, car: Car
) -> None:
    with pytest.raises(DBAPIError, match="uq_vehicle_ownerships_current"):
        await insert_period(engines, car, car.luis, "clock_timestamp()", None)


@pytest.mark.asyncio
async def test_two_periods_cannot_overlap_even_when_closed(
    engines: Engines, car: Car
) -> None:
    """El índice parcial solo mira los abiertos. Un periodo cerrado que se mete
    dentro del de María (una "corrección" de fechas a mano) lo para EXCLUDE."""
    with pytest.raises(DBAPIError, match="ex_vehicle_ownerships_no_overlap"):
        await insert_period(
            engines,
            car,
            car.luis,
            "clock_timestamp() - interval '6 months'",
            "clock_timestamp() - interval '3 months'",
        )


@pytest.mark.asyncio
async def test_periods_that_touch_do_not_overlap(engines: Engines, car: Car) -> None:
    """[inicio, fin): un periodo que acaba justo cuando empieza otro no lo pisa.
    Es lo que hace el cambio de titular."""
    async with engines.platform.begin() as conn:
        started = await conn.scalar(
            text("SELECT started_at FROM vehicle_ownerships WHERE id = :p"),
            {"p": car.period_id},
        )
    await insert_period(
        engines,
        car,
        car.luis,
        f"'{started.isoformat()}'::timestamptz - interval '2 years'",
        f"'{started.isoformat()}'::timestamptz",
    )


@pytest.mark.asyncio
async def test_a_period_cannot_end_before_it_starts(engines: Engines, car: Car) -> None:
    with pytest.raises(DBAPIError, match="ck_vehicle_ownerships_ended_after_started"):
        await insert_period(
            engines,
            car,
            car.luis,
            "clock_timestamp() - interval '3 years'",
            "clock_timestamp() - interval '4 years'",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["owner", "platform"])
async def test_a_closed_period_never_changes_again(
    engines: Engines, car: Car, role: str
) -> None:
    """Se cierra una vez y queda así: ni otro fin, ni otro cliente, con ningún
    rol, tampoco el dueño de las tablas."""
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "UPDATE vehicle_ownerships SET ended_at = clock_timestamp() WHERE id = :p"
            ),
            {"p": car.period_id},
        )
    engine = engines.owner if role == "owner" else engines.platform
    for change in ("ended_at = clock_timestamp()", "client_id = :luis"):
        async with engine.begin() as conn:
            await set_workshops(conn, car.workshop_id)
            with pytest.raises(DBAPIError, match="can only be closed once"):
                await conn.execute(
                    text(f"UPDATE vehicle_ownerships SET {change} WHERE id = :p"),
                    {"p": car.period_id, "luis": car.luis},
                )


@pytest.mark.asyncio
async def test_an_open_period_cannot_change_hands_by_update(
    engines: Engines, car: Car
) -> None:
    """Cambiar de titular es cerrar y abrir otro, no reescribir el cliente de un
    periodo: el historial de quién fue titular se perdería."""
    async with engines.platform.begin() as conn:
        with pytest.raises(DBAPIError, match="can only be closed once"):
            await conn.execute(
                text("UPDATE vehicle_ownerships SET client_id = :luis WHERE id = :p"),
                {"p": car.period_id, "luis": car.luis},
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE vehicle_ownerships SET client_id = :luis",
        "UPDATE vehicle_ownerships SET started_at = clock_timestamp()",
        "DELETE FROM vehicle_ownerships",
        "TRUNCATE vehicle_ownerships",
        "DELETE FROM vehicles",
        "TRUNCATE vehicles",
    ],
)
async def test_the_app_role_can_only_close_periods_and_never_delete(
    engines: Engines, car: Car, statement: str
) -> None:
    """Migración 0005vehicles: de un periodo, axtton_app solo escribe `ended_at`;
    ni periodos ni vehículos se borran (sus órdenes apuntarán a ellos)."""
    async with engines.app.begin() as conn:
        await set_workshops(conn, car.workshop_id)
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text(statement), {"luis": car.luis})


@pytest.mark.asyncio
async def test_the_app_role_can_close_a_period(engines: Engines, car: Car) -> None:
    """Prueba de control de la anterior: lo que sí puede hacer, lo puede hacer."""
    async with engines.app.begin() as conn:
        await set_workshops(conn, car.workshop_id)
        closed = await conn.execute(
            text(
                "UPDATE vehicle_ownerships SET ended_at = clock_timestamp() WHERE id = :p"
            ),
            {"p": car.period_id},
        )
    assert closed.rowcount == 1


@pytest.mark.asyncio
async def test_a_period_cannot_join_a_vehicle_and_a_client_of_two_workshops(
    engines: Engines, car: Car, two_workshops: TwoWorkshops
) -> None:
    """FK compuestas: aunque se escriba con el rol que se salta RLS, un periodo
    del taller B no puede apuntar al vehículo de A (ni a su cliente).

    El periodo es antiguo y cerrado: así no choca antes con el índice de "un
    titular actual" ni con EXCLUDE, que Postgres comprueba antes que las FK."""
    async with engines.platform.begin() as conn:
        with pytest.raises(DBAPIError, match="fk_vehicle_ownerships"):
            await conn.execute(
                text(
                    "INSERT INTO vehicle_ownerships"
                    " (workshop_id, vehicle_id, client_id, started_at, ended_at)"
                    " VALUES (:b, :v, :c, clock_timestamp() - interval '5 years',"
                    " clock_timestamp() - interval '4 years')"
                ),
                {"b": two_workshops.b, "v": car.vehicle_id, "c": car.luis},
            )
