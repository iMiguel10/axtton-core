"""El worker y su primera tarea programada (F5 paso 1).

- El worker carga, con su cola y sus tareas programadas.
- Borrar los enlaces del portal caducados: el planificador solo busca talleres
  (axtton_platform), y cada taller se borra en su transacción, con axtton_app y
  RLS. Un enlace que aún vale no lo borra nadie, con ningún rol (trigger).
"""

from secrets import token_bytes
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.domain.portal import LINK_RETENTION
from app.jobs import maintenance
from app.jobs.context import WorkerContext
from app.jobs.maintenance import purge_portal_links
from app.platform.scheduler import workshops_with_expired_links
from tests.conftest import Engines, TwoWorkshops
from tests.test_concurrency import dispose_global_engines  # noqa: F401 (autouse)
from tests.test_portal_auth import add_client, new_email
from tests.test_rls import set_workshops

# SAQ pasa su contexto; esta tarea no usa nada de él.
NO_CONTEXT = cast(WorkerContext, {})


async def add_link(
    engines: Engines, workshop_id: UUID, *, expired_ago: str | None, used: bool = False
) -> UUID:
    """Un enlace que caducó hace `expired_ago` (un intervalo de Postgres), o que
    aún vale si es None. Se escribe con la plataforma, con su `created_at` en el
    pasado: así cumple el CHECK de que caduca después de crearse."""
    client_id = await add_client(engines, workshop_id, new_email())
    created = (
        "clock_timestamp()"
        if expired_ago is None
        else f"clock_timestamp() - interval '{expired_ago}' - interval '15 minutes'"
    )
    async with engines.platform.begin() as conn:
        link_id = await conn.scalar(
            text(
                "INSERT INTO portal_links (workshop_id, client_id, token_hash,"
                " created_at, expires_at, used_at)"
                f" VALUES (:w, :c, :h, {created},"
                f" {created} + interval '15 minutes',"
                f" CASE WHEN :used THEN {created} END)"
                " RETURNING id"
            ),
            {"w": workshop_id, "c": client_id, "h": token_bytes(32), "used": used},
        )
    assert isinstance(link_id, UUID)
    return link_id


async def remaining(engines: Engines) -> set[UUID]:
    async with engines.platform.connect() as conn:
        rows = await conn.scalars(text("SELECT id FROM portal_links"))
        return set(rows)


def test_the_worker_loads_with_its_scheduled_tasks() -> None:
    """`saq app.worker.settings` importa esto: si fallara, el worker no arranca."""
    from app.worker import settings

    crons = {job.function.__name__: job for job in settings["cron_jobs"]}
    assert set(crons) == {
        "purge_portal_links",
        "expire_quotes",
        "dispatch_notifications",
        "expire_abandoned_notifications",
    }
    # Una pasada al día, de madrugada, con un solo intento: si falla, la recoge
    # la del día siguiente.
    assert crons["purge_portal_links"].cron == "40 3 * * *"
    assert crons["purge_portal_links"].retries == 1
    # Cada hora, como en la arquitectura (§8, "Caducidad de presupuestos").
    assert crons["expire_quotes"].cron == "5 * * * *"


@pytest.mark.asyncio
async def test_purge_deletes_only_links_expired_longer_than_the_retention(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    a, b = two_workshops.a, two_workshops.b
    old_used = await add_link(engines, a, expired_ago="8 days", used=True)
    old_unused = await add_link(engines, b, expired_ago="8 days")
    recent = await add_link(engines, a, expired_ago="6 days")
    valid = await add_link(engines, b, expired_ago=None)

    assert await purge_portal_links(NO_CONTEXT) == 2
    assert await remaining(engines) == {recent, valid}
    assert old_used not in await remaining(engines)
    assert old_unused not in await remaining(engines)
    # Otra pasada no encuentra nada: ejecutarla dos veces es inocuo.
    assert await purge_portal_links(NO_CONTEXT) == 0


@pytest.mark.asyncio
async def test_the_scheduler_only_finds_workshops_with_something_to_delete(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    await add_link(engines, two_workshops.a, expired_ago="30 days")
    await add_link(engines, two_workshops.b, expired_ago="1 day")
    assert await workshops_with_expired_links(LINK_RETENTION) == [two_workshops.a]


@pytest.mark.asyncio
async def test_one_workshop_failing_does_not_stop_the_others(
    engines: Engines, two_workshops: TwoWorkshops, monkeypatch: pytest.MonkeyPatch
) -> None:
    await add_link(engines, two_workshops.a, expired_ago="8 days")
    survivor = await add_link(engines, two_workshops.b, expired_ago="8 days")
    real = maintenance.portal_auth_service.purge_expired_links

    async def failing_for_b(workshop_id: UUID) -> int:
        if workshop_id == two_workshops.b:
            raise RuntimeError("fallo de prueba")
        return await real(workshop_id)

    monkeypatch.setattr(
        maintenance.portal_auth_service, "purge_expired_links", failing_for_b
    )
    assert await purge_portal_links(NO_CONTEXT) == 1
    assert await remaining(engines) == {survivor}


@pytest.mark.asyncio
async def test_a_workshop_purge_never_touches_another_workshop(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    """Con el taller A fijado, un DELETE sin condiciones no ve los de B (RLS)."""
    of_b = await add_link(engines, two_workshops.b, expired_ago="8 days")
    async with engines.app.begin() as conn:
        await set_workshops(conn, two_workshops.a)
        deleted = await conn.execute(text("DELETE FROM portal_links"))
    assert deleted.rowcount == 0
    assert await remaining(engines) == {of_b}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform", "owner"])
async def test_a_link_that_still_works_cannot_be_deleted_by_anyone(
    engines: Engines, two_workshops: TwoWorkshops, role: str
) -> None:
    """Cuánto se guarda lo decide el código; que no se borre uno que aún vale, el
    trigger, con cualquier rol (también un DELETE sin WHERE)."""
    valid = await add_link(engines, two_workshops.a, expired_ago=None)
    engine = getattr(engines, role)
    async with engine.connect() as conn:
        if role == "app":
            await set_workshops(conn, two_workshops.a)
        if role == "owner":
            # El dueño obedece la RLS forzada; la quita en su transacción para
            # llegar a la fila, y el trigger lo para igual.
            await conn.execute(
                text("ALTER TABLE portal_links NO FORCE ROW LEVEL SECURITY")
            )
        with pytest.raises(DBAPIError, match="has not expired yet"):
            await conn.execute(text("DELETE FROM portal_links"))
        await conn.rollback()
    assert await remaining(engines) == {valid}
