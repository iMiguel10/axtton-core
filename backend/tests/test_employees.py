"""Empleados y roles desde el taller (RF-03 a RF-06, RNF-03, RNF-15, RNF-16)."""

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.api.deps import get_email_sender
from app.infra.email import InMemoryEmailSender
from app.main import app
from app.scripts.reset_data import truncate_all
from tests.conftest import Engines
from tests.test_invitations import PASSWORD, Invited, accept, bearer, new_workshop


@dataclass(frozen=True)
class AdminSession:
    invited: Invited
    headers: dict[str, str]


@pytest_asyncio.fixture
async def outbox() -> AsyncIterator[InMemoryEmailSender]:
    sender = InMemoryEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    yield sender
    app.dependency_overrides.pop(get_email_sender, None)


@pytest_asyncio.fixture
async def admin(client: AsyncClient) -> AdminSession:
    """Ana, administradora con acceso, trabajando en su taller."""
    await truncate_all()
    invited = await new_workshop()
    assert await accept(client, invited) == 204
    headers = {
        **await bearer(client, invited.email),
        "X-Workshop-Id": invited.workshop_id,
    }
    return AdminSession(invited, headers)


async def employees(client: AsyncClient, admin: AdminSession) -> list[dict]:
    response = await client.get("/api/v1/workshop/employees", headers=admin.headers)
    assert response.status_code == 200
    result: list[dict] = response.json()
    return result


async def by_name(client: AsyncClient, admin: AdminSession, name: str) -> dict:
    return next(e for e in await employees(client, admin) if e["name"] == name)


async def add_mechanic(
    client: AsyncClient, admin: AdminSession, name: str = "Juan"
) -> str:
    response = await client.post(
        "/api/v1/workshop/employees",
        json={"name": name, "role": "mechanic", "hourly_cost_cents": 2500},
        headers=admin.headers,
    )
    assert response.status_code == 201
    employee_id: str = response.json()["id"]
    return employee_id


async def invite_and_accept(
    client: AsyncClient,
    admin: AdminSession,
    outbox: InMemoryEmailSender,
    employee_id: str,
) -> dict[str, str]:
    """Invita a la ficha, la persona acepta y devuelve sus cabeceras en el taller."""
    email = f"juan-{employee_id[:8]}@example.com"
    response = await client.post(
        f"/api/v1/workshop/employees/{employee_id}/invitation",
        json={"email": email},
        headers=admin.headers,
    )
    assert response.json() == {"invitation_email_queued": True}
    link = f"/invitations/{admin.invited.workshop_id}/"
    token = outbox.sent[-1].body.split(link, 1)[1].split()[0]
    assert await accept(client, Invited(admin.invited.workshop_id, email, token)) == 204
    return {
        **await bearer(client, email, PASSWORD),
        "X-Workshop-Id": admin.invited.workshop_id,
    }


@pytest.mark.asyncio
async def test_a_card_without_access_exists_and_admins_see_costs(
    client: AsyncClient, admin: AdminSession
) -> None:
    await add_mechanic(client, admin)
    juan = await by_name(client, admin, "Juan")
    assert (juan["role"], juan["has_access"], juan["hourly_cost_cents"]) == (
        "mechanic",
        False,
        2500,
    )


@pytest.mark.asyncio
async def test_an_invited_mechanic_works_with_mechanic_permissions(
    client: AsyncClient, admin: AdminSession, outbox: InMemoryEmailSender
) -> None:
    mechanic = await invite_and_accept(
        client, admin, outbox, await add_mechanic(client, admin)
    )

    active = await client.get("/api/v1/workshop/active", headers=mechanic)
    assert active.json()["role"] == "mechanic"
    # RNF-03: el permiso sale del rol en ESTE taller, decidido en un solo sitio.
    forbidden = await client.get("/api/v1/workshop/employees", headers=mechanic)
    assert forbidden.status_code == 403
    assert forbidden.json() == {"code": "not_allowed"}


@pytest.mark.asyncio
async def test_reinviting_invalidates_the_previous_link(
    client: AsyncClient, admin: AdminSession, outbox: InMemoryEmailSender
) -> None:
    employee_id = await add_mechanic(client, admin)
    for _ in range(2):
        await client.post(
            f"/api/v1/workshop/employees/{employee_id}/invitation",
            json={"email": "juan@example.com"},
            headers=admin.headers,
        )
    link = f"/invitations/{admin.invited.workshop_id}/"
    first, second = (e.body.split(link, 1)[1].split()[0] for e in outbox.sent)
    assert (await client.get(f"/api/v1{link}{first}")).status_code == 404
    assert (await client.get(f"/api/v1{link}{second}")).status_code == 200


@pytest.mark.asyncio
async def test_a_stale_version_does_not_overwrite_someone_elses_change(
    client: AsyncClient, admin: AdminSession
) -> None:
    """RNF-15: dos personas editan la misma ficha; la segunda no pisa a la primera."""
    employee_id = await add_mechanic(client, admin)
    version = (await by_name(client, admin, "Juan"))["version"]
    url = f"/api/v1/workshop/employees/{employee_id}"

    first = await client.patch(
        url,
        json={"version": version, "position": "Jefe de taller"},
        headers=admin.headers,
    )
    second = await client.patch(
        url, json={"version": version, "position": "Aprendiz"}, headers=admin.headers
    )

    assert first.status_code == 204
    assert second.status_code == 409
    assert second.json() == {"code": "modified_by_someone_else"}
    assert (await by_name(client, admin, "Juan"))["position"] == "Jefe de taller"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [{"role": "mechanic"}, {"active": False}, "remove_access"],
    ids=["demote", "deactivate", "remove_access"],
)
async def test_rf05_the_last_admin_cannot_leave_the_workshop_without_admins(
    client: AsyncClient, admin: AdminSession, change: object
) -> None:
    ana = await by_name(client, admin, "Ana López")
    url = f"/api/v1/workshop/employees/{ana['id']}"
    if change == "remove_access":
        response = await client.post(
            f"{url}/access/remove",
            json={"version": ana["version"]},
            headers=admin.headers,
        )
    else:
        assert isinstance(change, dict)
        response = await client.patch(
            url, json={"version": ana["version"], **change}, headers=admin.headers
        )
    assert response.json() == {"code": "last_admin"}
    # Y no cambió nada: la transacción entera se deshizo.
    after = await by_name(client, admin, "Ana López")
    assert (after["role"], after["active"], after["has_access"]) == (
        "admin",
        True,
        True,
    )


@pytest.mark.asyncio
async def test_with_a_second_admin_the_first_one_can_step_down(
    client: AsyncClient, admin: AdminSession, outbox: InMemoryEmailSender
) -> None:
    employee_id = await add_mechanic(client, admin, "Marta")
    version = (await by_name(client, admin, "Marta"))["version"]
    await client.patch(
        f"/api/v1/workshop/employees/{employee_id}",
        json={"version": version, "role": "admin"},
        headers=admin.headers,
    )
    await invite_and_accept(client, admin, outbox, employee_id)
    ana = await by_name(client, admin, "Ana López")
    response = await client.patch(
        f"/api/v1/workshop/employees/{ana['id']}",
        json={"version": ana["version"], "role": "mechanic"},
        headers=admin.headers,
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_removing_access_cuts_the_next_request_and_is_audited(
    client: AsyncClient,
    admin: AdminSession,
    outbox: InMemoryEmailSender,
    engines: Engines,
) -> None:
    employee_id = await add_mechanic(client, admin)
    mechanic = await invite_and_accept(client, admin, outbox, employee_id)
    assert (
        await client.get("/api/v1/workshop/active", headers=mechanic)
    ).status_code == 200

    version = (await by_name(client, admin, "Juan"))["version"]
    response = await client.post(
        f"/api/v1/workshop/employees/{employee_id}/access/remove",
        json={"version": version},
        headers=admin.headers,
    )
    assert response.status_code == 204
    # La ficha se queda; la sesión de Juan sigue viva, pero ya no entra en el taller.
    assert (await by_name(client, admin, "Juan"))["has_access"] is False
    assert (
        await client.get("/api/v1/workshop/active", headers=mechanic)
    ).status_code == 404

    async with engines.platform.connect() as conn:
        actions = (
            await conn.scalars(
                text("SELECT action FROM audit_log WHERE target_id = :e ORDER BY seq"),
                {"e": employee_id},
            )
        ).all()
    assert actions == [
        "employee_created",
        "invitation_sent",
        "invitation_accepted",
        "access_removed",
    ]


@pytest.mark.asyncio
async def test_role_changes_are_audited_with_before_and_after(
    client: AsyncClient, admin: AdminSession, engines: Engines
) -> None:
    employee_id = await add_mechanic(client, admin)
    version = (await by_name(client, admin, "Juan"))["version"]
    await client.patch(
        f"/api/v1/workshop/employees/{employee_id}",
        json={"version": version, "role": "admin", "hourly_cost_cents": 3000},
        headers=admin.headers,
    )
    async with engines.platform.connect() as conn:
        details = await conn.scalar(
            text("SELECT details FROM audit_log WHERE action = 'employee_updated'")
        )
    assert details == {"role": ["mechanic", "admin"], "hourly_cost_cents": [2500, 3000]}
