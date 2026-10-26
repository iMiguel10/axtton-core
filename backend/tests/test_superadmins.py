"""Invitar a otro superadministrador desde la aplicación (RF-110)."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.api.deps import get_email_sender
from app.infra.email import InMemoryEmailSender
from app.main import app
from app.scripts.reset_data import truncate_all
from tests.conftest import Account, Engines, sign_in
from tests.test_admin import MakeAccount

PASSWORD = "contraseña-de-eva-1"


@pytest_asyncio.fixture
async def outbox() -> AsyncIterator[InMemoryEmailSender]:
    sender = InMemoryEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    yield sender
    app.dependency_overrides.pop(get_email_sender, None)


@pytest_asyncio.fixture
async def superadmin(client: AsyncClient, make_account: MakeAccount) -> dict[str, str]:
    await truncate_all()
    token = await sign_in(client, await make_account("superadmin"))
    return {"Authorization": f"Bearer {token}"}


async def invite(
    client: AsyncClient,
    headers: dict[str, str],
    outbox: InMemoryEmailSender,
    email: str | None = None,
) -> tuple[str, str]:
    """Invita y devuelve (email, token del enlace)."""
    email = email or f"eva-{uuid4().hex[:8]}@example.com"
    response = await client.post(
        "/api/v1/admin/superadmins/invitations", json={"email": email}, headers=headers
    )
    assert response.status_code == 201, response.text
    assert response.json() == {"invitation_email_sent": True}
    assert outbox.sent[-1].to == email.lower()  # se guarda normalizado
    token = outbox.sent[-1].body.split("/superadmin-invitations/", 1)[1].split()[0]
    return email, token


async def accept(client: AsyncClient, token: str, password: str = PASSWORD) -> int:
    response = await client.post(
        f"/api/v1/superadmin-invitations/{token}/accept", json={"password": password}
    )
    return response.status_code


@pytest.mark.asyncio
async def test_an_invited_superadmin_can_sign_in_to_admin(
    client: AsyncClient, superadmin: dict[str, str], outbox: InMemoryEmailSender
) -> None:
    email, token = await invite(client, superadmin, outbox)

    shown = await client.get(f"/api/v1/superadmin-invitations/{token}")
    assert shown.json() == {"email": email}
    assert await accept(client, token) == 204

    new = {
        "Authorization": f"Bearer {await sign_in(client, Account(email, PASSWORD, ''))}"
    }
    me = await client.get("/api/v1/admin/me", headers=new)
    assert me.json() == {"actor": "superadmin"}
    # Y no es personal: /workshop lo rechaza.
    assert (await client.get("/api/v1/workshop/me", headers=new)).status_code == 403

    listed = (await client.get("/api/v1/admin/superadmins", headers=superadmin)).json()
    assert email in [s["email"] for s in listed["superadmins"]]
    assert listed["pending_invitations"] == []

    actions = [
        e["action"]
        for e in (await client.get("/api/v1/admin/audit", headers=superadmin)).json()[
            "entries"
        ]
    ]
    assert actions[:2] == ["superadmin_created", "superadmin_invited"]


@pytest.mark.asyncio
async def test_a_link_works_only_once(
    client: AsyncClient, superadmin: dict[str, str], outbox: InMemoryEmailSender
) -> None:
    _, token = await invite(client, superadmin, outbox)
    assert await accept(client, token) == 204
    response = await client.post(
        f"/api/v1/superadmin-invitations/{token}/accept", json={"password": PASSWORD}
    )
    assert response.status_code == 409
    assert response.json() == {"code": "invitation_already_accepted"}


@pytest.mark.asyncio
async def test_inviting_again_voids_the_previous_link(
    client: AsyncClient, superadmin: dict[str, str], outbox: InMemoryEmailSender
) -> None:
    email, old = await invite(client, superadmin, outbox)
    _, new = await invite(client, superadmin, outbox, email.upper())
    assert await accept(client, old) == 404
    assert await accept(client, new) == 204


@pytest.mark.asyncio
async def test_an_expired_link_does_not_work(
    client: AsyncClient,
    superadmin: dict[str, str],
    outbox: InMemoryEmailSender,
    engines: Engines,
) -> None:
    _, token = await invite(client, superadmin, outbox)
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE superadmin_invitations SET expires_at = now() - interval '1s'")
        )
    assert (
        await client.get(f"/api/v1/superadmin-invitations/{token}")
    ).status_code == 404
    assert await accept(client, token) == 404


@pytest.mark.asyncio
async def test_a_staff_account_cannot_become_superadmin(
    client: AsyncClient,
    superadmin: dict[str, str],
    outbox: InMemoryEmailSender,
    make_account: MakeAccount,
) -> None:
    """Un superadministrador nunca es empleado (arquitectura §2): con el email de
    alguien del personal, ni con su contraseña ni sin ella."""
    staff = await make_account("staff")
    _, token = await invite(client, superadmin, outbox, staff.email)

    assert await accept(client, token, "no-es-la-suya-1") == 403
    response = await client.post(
        f"/api/v1/superadmin-invitations/{token}/accept",
        json={"password": staff.password},
    )
    assert response.status_code == 409
    assert response.json() == {"code": "staff_cannot_be_superadmin"}

    # Sigue siendo personal y nada más.
    token_staff = await sign_in(client, staff)
    me = await client.get(
        "/api/v1/admin/me", headers={"Authorization": f"Bearer {token_staff}"}
    )
    assert me.status_code == 403


@pytest.mark.asyncio
async def test_an_unknown_link_says_nothing(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/superadmin-invitations/{uuid4().hex}")
    assert response.status_code == 404
    assert response.json() == {"code": "invitation_not_found"}


@pytest.mark.asyncio
async def test_the_application_role_cannot_read_superadmin_invitations(
    engines: Engines,
) -> None:
    """La tabla es de plataforma: ni axtton_app puede leer sus hashes."""
    async with engines.app.connect() as conn:
        with pytest.raises(ProgrammingError, match="permission denied"):
            await conn.execute(text("SELECT * FROM superadmin_invitations"))
