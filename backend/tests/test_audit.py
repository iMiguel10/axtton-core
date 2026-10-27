"""Consulta del registro de auditoría (RNF-16): el administrador ve el de su
taller y el superadministrador el de la plataforma. Ninguno ve el del otro, ni
un taller el de otro taller.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.api.deps import get_email_sender
from app.infra.email import InMemoryEmailSender
from app.main import app
from app.scripts.reset_data import truncate_all
from tests.conftest import Account, sign_in
from tests.test_admin import MakeAccount
from tests.test_employees import AdminSession, add_mechanic, invite_and_accept
from tests.test_invitations import accept, bearer, new_workshop


@pytest_asyncio.fixture
async def outbox() -> AsyncIterator[InMemoryEmailSender]:
    sender = InMemoryEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    yield sender
    app.dependency_overrides.pop(get_email_sender, None)


async def open_workshop(client: AsyncClient, name: str) -> AdminSession:
    invited = await new_workshop(name)
    assert await accept(client, invited) == 204
    headers = {
        **await bearer(client, invited.email),
        "X-Workshop-Id": invited.workshop_id,
    }
    return AdminSession(invited, headers)


async def audit(client: AsyncClient, headers: dict[str, str], **params: int) -> dict:
    response = await client.get(
        "/api/v1/workshop/audit", headers=headers, params=params
    )
    assert response.status_code == 200, response.text
    page: dict = response.json()
    return page


@pytest_asyncio.fixture
async def admin(client: AsyncClient) -> AdminSession:
    await truncate_all()
    return await open_workshop(client, "Talleres Pérez")


@pytest.mark.asyncio
async def test_the_admin_sees_who_did_what_newest_first(
    client: AsyncClient, admin: AdminSession
) -> None:
    juan = await add_mechanic(client, admin)
    response = await client.patch(
        f"/api/v1/workshop/employees/{juan}",
        json={"version": 1, "role": "admin"},
        headers=admin.headers,
    )
    assert response.status_code == 204

    entries = (await audit(client, admin.headers))["entries"]
    assert [e["action"] for e in entries] == [
        "employee_updated",
        "employee_created",
        "invitation_accepted",
    ]
    change = entries[0]
    assert change["actor"] == "Ana López"
    assert change["target_type"] == "employee"
    assert change["target_name"] == "Juan"
    assert change["details"] == {"role": ["mechanic", "admin"]}
    seqs = [e["seq"] for e in entries]
    assert seqs == sorted(seqs, reverse=True)


@pytest.mark.asyncio
async def test_platform_entries_never_reach_the_workshop(
    client: AsyncClient, admin: AdminSession
) -> None:
    """El alta del taller es de plataforma (workshop_id nulo): ni su propio
    taller la ve, aunque sea sobre él."""
    actions = {e["action"] for e in (await audit(client, admin.headers))["entries"]}
    assert "workshop_created" not in actions


@pytest.mark.asyncio
async def test_a_workshop_never_sees_another_workshops_log(
    client: AsyncClient, admin: AdminSession
) -> None:
    other = await open_workshop(client, "Taller B")
    await add_mechanic(client, other, "Secreto")

    entries = (await audit(client, admin.headers))["entries"]
    assert all(e["target_name"] != "Secreto" for e in entries)
    assert [e["action"] for e in entries] == ["invitation_accepted"]

    # Ni pidiendo el de B con la cabecera de B: Ana no trabaja allí.
    response = await client.get(
        "/api/v1/workshop/audit",
        headers={**admin.headers, "X-Workshop-Id": other.invited.workshop_id},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_mechanic_cannot_read_the_log(
    client: AsyncClient, admin: AdminSession, outbox: InMemoryEmailSender
) -> None:
    juan = await add_mechanic(client, admin)
    juan_headers = await invite_and_accept(client, admin, outbox, juan)
    response = await client.get("/api/v1/workshop/audit", headers=juan_headers)
    assert response.status_code == 403
    assert response.json() == {"code": "not_allowed"}


@pytest.mark.asyncio
async def test_the_log_is_paged_by_seq(
    client: AsyncClient, admin: AdminSession
) -> None:
    for name in ("Uno", "Dos", "Tres"):
        await add_mechanic(client, admin, name)

    first = await audit(client, admin.headers, limit=2)
    assert [e["target_name"] for e in first["entries"]] == ["Tres", "Dos"]
    assert first["next_before"] == first["entries"][-1]["seq"]

    second = await audit(client, admin.headers, limit=2, before=first["next_before"])
    assert [e["target_name"] for e in second["entries"]] == ["Uno", "Ana López"]
    assert second["next_before"] is None


# --- Plataforma ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_superadmin_sees_the_platform_log_and_nothing_operational(
    client: AsyncClient, make_account: MakeAccount, outbox: InMemoryEmailSender
) -> None:
    await truncate_all()
    account: Account = await make_account("superadmin")
    headers = {"Authorization": f"Bearer {await sign_in(client, account)}"}
    created = await client.post(
        "/api/v1/admin/workshops",
        json={
            "name": "Taller Norte",
            "admin_name": "Eva",
            "admin_email": "eva-norte@example.com",
        },
        headers=headers,
    )
    workshop_id = created.json()["workshop_id"]
    await client.patch(
        f"/api/v1/admin/workshops/{workshop_id}",
        json={"max_employees_with_access": 3},
        headers=headers,
    )
    # Algo operativo dentro de un taller, que el superadministrador no debe ver.
    other = await open_workshop(client, "Taller Sur")
    await add_mechanic(client, other, "Operativo")

    response = await client.get("/api/v1/admin/audit", headers=headers)
    assert response.status_code == 200
    entries = response.json()["entries"]
    actions = {e["action"] for e in entries}
    assert "employee_created" not in actions
    assert "invitation_accepted" not in actions

    norte = [e for e in entries if e["target_name"] == "Taller Norte"]
    assert [e["action"] for e in norte] == ["workshop_updated", "workshop_created"]
    update = norte[0]
    assert update["actor"] == account.email
    assert update["target_name"] == "Taller Norte"
    assert update["details"] == {"max_employees_with_access": [5, 3]}


@pytest.mark.asyncio
async def test_staff_cannot_read_the_platform_log(
    client: AsyncClient, admin: AdminSession
) -> None:
    response = await client.get("/api/v1/admin/audit", headers=admin.headers)
    assert response.status_code == 403
