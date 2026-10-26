"""Carreras con DOS transacciones reales contra Postgres (arquitectura §10).

Cada prueba abre dos transacciones de verdad y las intercala a mano: la primera
hace su cambio sin confirmar, la segunda arranca en una tarea, y solo entonces se
confirma la primera. Así el resultado no depende de la suerte del planificador:
si el código bloquea lo que debe, la segunda espera; si no, avanza y se ve.

Tres de ellas (el último administrador, el límite de plazas y el taller único)
demostraron al cerrar F1 carreras reales; se arreglaron con un bloqueo consultivo
por taller (repositories/employees.py::lock_staff) y quedan como pruebas de
regresión.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core.db import SessionFactory, set_workshops
from app.core.errors import AppError, ConflictError
from app.core.tokens import hash_token
from app.infra.email import InMemoryEmailSender
from tests.conftest import Account, Engines, TwoWorkshops

MakeAccount = Callable[[str], Awaitable[Account]]
PASSWORD = "contraseña-de-prueba-1"
# Lo que se le deja a la segunda transacción para avanzar (o quedarse bloqueada)
# antes de confirmar la primera.
GRACE = 0.5


@pytest_asyncio.fixture(autouse=True)
async def dispose_global_engines() -> AsyncIterator[None]:
    """Estas pruebas usan los engines globales sin pasar por el fixture `client`,
    que es quien los cierra: sus conexiones quedarían ligadas a este event loop
    y la prueba siguiente fallaría con "Event loop is closed" (CLAUDE.md §8)."""
    yield
    from app.core import db
    from app.platform.db import platform_engine

    await db.engine.dispose()
    await platform_engine.dispose()


@asynccontextmanager
async def open_transaction(workshop_id: UUID) -> AsyncIterator[AsyncSession]:
    """Una transacción de taller que NO se confirma sola: la prueba decide cuándo."""
    async with SessionFactory() as session:
        await session.begin()
        await set_workshops(session, [workshop_id])
        try:
            yield session
        finally:
            if session.in_transaction():
                await session.rollback()


async def finish(session: AsyncSession, work: "asyncio.Task[Any]") -> object:
    """Espera a la segunda transacción y la confirma si terminó bien.

    Devuelve lo que devolvió o la excepción que lanzó, para que la prueba lo mire.
    """
    try:
        result = await asyncio.wait_for(work, timeout=10)
    except (AppError, StaleDataError) as error:
        await session.rollback()
        return error
    await session.commit()
    return result


@dataclass(frozen=True)
class StaffMember:
    employee_id: UUID
    user_id: UUID


async def employee_with_access(
    engines: Engines, make_account: MakeAccount, workshop_id: UUID, role: str
) -> StaffMember:
    account = await make_account("staff")
    async with engines.platform.begin() as conn:
        user_id = await conn.scalar(
            text("SELECT id FROM users WHERE supertokens_user_id = :s"),
            {"s": account.supertokens_user_id},
        )
        employee_id = await conn.scalar(
            text(
                "INSERT INTO employees (workshop_id, user_id, name, role)"
                " VALUES (:w, :u, :n, :r) RETURNING id"
            ),
            {"w": workshop_id, "u": user_id, "n": account.email, "r": role},
        )
    return StaffMember(employee_id, user_id)


async def active_admins_with_access(engines: Engines, workshop_id: UUID) -> int:
    async with engines.platform.connect() as conn:
        count: int = await conn.scalar(
            text(
                "SELECT count(*) FROM employees WHERE workshop_id = :w"
                " AND role = 'admin' AND active AND user_id IS NOT NULL"
            ),
            {"w": workshop_id},
        )
    return count


# --- RF-05: nunca sin administrador --------------------------------------------


@pytest.mark.asyncio
async def test_rf05_two_admins_demoting_each_other_at_once_leave_an_admin(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    from app.services import employees as employee_service

    a = two_workshops.a
    # El admin del fixture no tiene cuenta: no cuenta para RF-05. Hay dos que sí.
    ana = await employee_with_access(engines, make_account, a, "admin")
    luis = await employee_with_access(engines, make_account, a, "admin")
    assert await active_admins_with_access(engines, a) == 2

    async def demote(session: AsyncSession, actor: StaffMember, target: UUID) -> None:
        await employee_service.update_employee(
            session,
            a,
            actor.user_id,
            target,
            expected_version=1,
            changes={"role": "mechanic"},
        )

    async with open_transaction(a) as first, open_transaction(a) as second:
        # Ana degrada a Luis (sin confirmar) y, a la vez, Luis degrada a Ana.
        await demote(first, ana, luis.employee_id)
        work = asyncio.create_task(demote(second, luis, ana.employee_id))
        await asyncio.sleep(GRACE)
        await first.commit()
        outcome = await finish(second, work)

    assert await active_admins_with_access(engines, a) >= 1, outcome


@pytest.mark.asyncio
async def test_two_edits_of_the_same_card_at_once_do_not_overwrite_each_other(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """RNF-15 con dos transacciones reales (la prueba de test_employees.py es
    secuencial): las dos leen la versión 1; la segunda espera al bloqueo de la
    fila y, al confirmarse la primera, su UPDATE ... WHERE version = 1 ya no
    encuentra la fila. Se rechaza, no pisa."""
    from app.services import employees as employee_service

    a = two_workshops.a
    ana = await employee_with_access(engines, make_account, a, "admin")
    target = two_workshops.admin_a

    async def rename(session: AsyncSession, name: str) -> None:
        await employee_service.update_employee(
            session, a, ana.user_id, target, expected_version=1, changes={"name": name}
        )
        await session.flush()

    async with open_transaction(a) as first, open_transaction(a) as second:
        await rename(first, "Primero")
        work = asyncio.create_task(rename(second, "Segundo"))
        await asyncio.sleep(GRACE)
        assert not work.done(), "la segunda debería esperar al bloqueo de la fila"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, StaleDataError | ConflictError), outcome
    async with engines.platform.connect() as conn:
        name = await conn.scalar(
            text("SELECT name FROM employees WHERE id = :e"), {"e": target}
        )
    assert name == "Primero"


# --- Aceptar invitaciones de empleado ------------------------------------------


async def pending_invitation(
    engines: Engines, workshop_id: UUID, role: str = "mechanic"
) -> tuple[str, str]:
    """Una ficha sin acceso con su invitación pendiente. Devuelve (email, token)."""
    email = f"inv-{uuid4().hex[:10]}@example.com"
    token = uuid4().hex
    async with engines.platform.begin() as conn:
        employee_id = await conn.scalar(
            text(
                "INSERT INTO employees (workshop_id, name, role)"
                " VALUES (:w, :n, :r) RETURNING id"
            ),
            {"w": workshop_id, "n": email, "r": role},
        )
        await conn.execute(
            text(
                "INSERT INTO invitations"
                " (workshop_id, employee_id, email, token_hash, expires_at)"
                " VALUES (:w, :e, :m, :h, clock_timestamp() + interval '1 day')"
            ),
            {"w": workshop_id, "e": employee_id, "m": email, "h": hash_token(token)},
        )
    return email, token


@pytest.mark.asyncio
async def test_the_same_invitation_accepted_twice_at_once_waits_for_the_first(
    engines: Engines, two_workshops: TwoWorkshops, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demuestra el FOR UPDATE de la invitación. La prueba con asyncio.gather de
    test_invitations.py daría [204, 409] también sin el bloqueo (la segunda
    chocaría luego con UNIQUE en users), así que no lo distingue. Aquí se mira
    que la segunda NI SIQUIERA llega a tocar SuperTokens mientras la primera sigue
    abierta."""
    from app.services import invitations as invitation_service

    a = two_workshops.a
    _, token = await pending_invitation(engines, a)
    calls: list[str] = []
    real = invitation_service.create_or_verify_account

    async def counting(email: str, password: str) -> str:
        calls.append(email)
        return await real(email, password)

    monkeypatch.setattr(invitation_service, "create_or_verify_account", counting)

    async with open_transaction(a) as first, open_transaction(a) as second:
        await invitation_service.accept(first, a, token, PASSWORD)
        work = asyncio.create_task(
            invitation_service.accept(second, a, token, PASSWORD)
        )
        await asyncio.sleep(GRACE)
        assert len(calls) == 1, "la segunda aceptación no esperó al bloqueo"
        assert not work.done()
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    assert outcome.code == "invitation_already_accepted"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_two_acceptances_with_one_free_seat_give_access_only_once(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    from app.services import invitations as invitation_service

    a = two_workshops.a
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE workshops SET max_employees_with_access = 1 WHERE id = :w"),
            {"w": a},
        )
    _, first_token = await pending_invitation(engines, a)
    _, second_token = await pending_invitation(engines, a)

    async with open_transaction(a) as first, open_transaction(a) as second:
        await invitation_service.accept(first, a, first_token, PASSWORD)
        work = asyncio.create_task(
            invitation_service.accept(second, a, second_token, PASSWORD)
        )
        await asyncio.sleep(GRACE)
        await first.commit()
        outcome = await finish(second, work)

    async with engines.platform.connect() as conn:
        with_access = await conn.scalar(
            text(
                "SELECT count(*) FROM employees"
                " WHERE workshop_id = :w AND user_id IS NOT NULL AND active"
            ),
            {"w": a},
        )
    assert with_access <= 1, outcome


# --- Aceptar invitaciones de superadministrador ---------------------------------


@pytest.mark.asyncio
async def test_a_superadmin_invitation_accepted_twice_at_once_creates_one_account(
    client: AsyncClient, engines: Engines, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dos aceptaciones simultáneas del mismo enlace (RF-110): una entra, la otra
    recibe 409, y la segunda no llega a SuperTokens mientras la primera sigue
    abierta (el FOR UPDATE de platform/superadmins.py::accept)."""
    from app.infra import identity
    from app.platform import superadmins
    from app.scripts.reset_data import truncate_all

    await truncate_all()
    outbox = InMemoryEmailSender()
    email = f"eva-{uuid4().hex[:8]}@example.com"
    await superadmins.invite(email=email, invited_by="nadie", email_sender=outbox)
    token = outbox.sent[-1].body.split("/superadmin-invitations/", 1)[1].split()[0]

    inside = 0
    most_inside = 0
    real = identity.create_or_verify_account

    async def slow(email: str, password: str) -> str:
        # Ensancha la ventana: si no hubiera bloqueo, la otra entraría aquí también.
        nonlocal inside, most_inside
        inside += 1
        most_inside = max(most_inside, inside)
        try:
            await asyncio.sleep(GRACE)
            return await real(email, password)
        finally:
            inside -= 1

    monkeypatch.setattr(identity, "create_or_verify_account", slow)

    async def accept() -> int:
        response = await client.post(
            f"/api/v1/superadmin-invitations/{token}/accept",
            json={"password": PASSWORD},
        )
        return response.status_code

    results = await asyncio.gather(accept(), accept())

    assert sorted(results) == [204, 409]
    assert most_inside == 1
    async with engines.platform.connect() as conn:
        created = await conn.scalar(
            text("SELECT count(*) FROM audit_log WHERE action = 'superadmin_created'")
        )
        superadmins_count = await conn.scalar(
            text("SELECT count(*) FROM users WHERE kind = 'superadmin'")
        )
    assert (created, superadmins_count) == (1, 1)


# --- Modo de instalación de un solo taller (RF-111) ------------------------------


@pytest.mark.asyncio
async def test_single_installation_two_creations_at_once_make_one_workshop(
    engines: Engines, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.platform import workshops
    from app.scripts.reset_data import truncate_all

    await truncate_all()
    monkeypatch.setattr(get_settings(), "installation_mode", "single")

    # Punto de encuentro tras el recuento: si el código bloqueara antes de
    # contar, la segunda nunca llegaría aquí y la primera seguiría a los 2 s.
    arrived = 0
    both = asyncio.Event()
    real_transaction = workshops.platform_transaction

    @asynccontextmanager
    async def synced_transaction() -> AsyncIterator[AsyncSession]:
        async with real_transaction() as session:
            original_scalar = session.scalar
            first_call = True

            async def scalar(*args: Any, **kwargs: Any) -> Any:
                nonlocal arrived, first_call
                result = await original_scalar(*args, **kwargs)
                if first_call:
                    first_call = False
                    arrived += 1
                    if arrived == 2:
                        both.set()
                    try:
                        await asyncio.wait_for(both.wait(), timeout=2)
                    except TimeoutError:
                        pass
                return result

            session.scalar = scalar  # type: ignore[method-assign]
            yield session

    monkeypatch.setattr(workshops, "platform_transaction", synced_transaction)

    async def create(name: str) -> object:
        try:
            return await workshops.create_workshop(
                name=name,
                admin_name="Ana",
                admin_email=f"{name}@example.com",
                created_by="nadie",
                email_sender=InMemoryEmailSender(),
            )
        except ConflictError as error:
            return error

    try:
        outcomes = await asyncio.gather(create("uno"), create("dos"))
    finally:
        from app.platform.db import platform_engine

        await platform_engine.dispose()

    async with engines.platform.connect() as conn:
        count = await conn.scalar(text("SELECT count(*) FROM workshops"))
    assert count == 1, outcomes


# --- F2 ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_clients_with_one_email_at_once_give_a_409_not_a_500(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    """RF-10: la segunda alta no ve la primera sin confirmar y pasa la
    comprobación previa; su INSERT espera al índice único y, al confirmarse la
    primera, choca. Tiene que llegar como ConflictError, no como IntegrityError
    (que sería un 500)."""
    from app.services import clients as client_service

    a = two_workshops.a
    fields = {"name": "Ana", "phone": "600", "email": "ana@example.com"}

    async with open_transaction(a) as first, open_transaction(a) as second:
        await client_service.create_client(first, a, fields)
        work = asyncio.create_task(client_service.create_client(second, a, fields))
        await asyncio.sleep(GRACE)
        assert not work.done(), "la segunda debería esperar al índice único"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    assert outcome.code == "client_email_taken"
    async with engines.platform.connect() as conn:
        count = await conn.scalar(text("SELECT count(*) FROM clients"))
    assert count == 1
