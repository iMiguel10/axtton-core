"""Pruebas adversas de F1 que faltaban: enlaces anulados o cruzados, el rol que
sale del taller activo, caminos de error que no deben acabar en 500 y lo que
SuperTokens expone por su cuenta.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.api.deps import get_email_sender
from app.infra.email import InMemoryEmailSender
from app.main import app
from app.platform import superadmins
from app.scripts.reset_data import truncate_all
from tests.conftest import Account, Engines, sign_in
from tests.test_auth import ALLOWED_PREFIX, protected_routes
from tests.test_employees import AdminSession, add_mechanic, by_name
from tests.test_invitations import (
    PASSWORD,
    Invited,
    accept,
    bearer,
    new_workshop,
)

MakeAccount = Callable[[str], Awaitable[Account]]


@pytest_asyncio.fixture
async def outbox() -> AsyncIterator[InMemoryEmailSender]:
    sender = InMemoryEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    yield sender
    app.dependency_overrides.pop(get_email_sender, None)


@pytest_asyncio.fixture
async def admin(client: AsyncClient) -> AdminSession:
    await truncate_all()
    invited = await new_workshop()
    assert await accept(client, invited) == 204
    headers = {
        **await bearer(client, invited.email),
        "X-Workshop-Id": invited.workshop_id,
    }
    return AdminSession(invited, headers)


async def invite(
    client: AsyncClient,
    admin: AdminSession,
    outbox: InMemoryEmailSender,
    employee_id: str,
    email: str,
) -> Invited:
    response = await client.post(
        f"/api/v1/workshop/employees/{employee_id}/invitation",
        json={"email": email},
        headers=admin.headers,
    )
    assert response.status_code == 200, response.text
    link = f"/invitations/{admin.invited.workshop_id}/"
    token = outbox.sent[-1].body.split(link, 1)[1].split()[0]
    return Invited(admin.invited.workshop_id, email, token)


async def can_sign_in(client: AsyncClient, email: str, password: str) -> bool:
    response = await client.post(
        "/api/auth/signin",
        headers={"st-auth-mode": "header"},
        json={
            "formFields": [
                {"id": "email", "value": email},
                {"id": "password", "value": password},
            ]
        },
    )
    return bool(response.json()["status"] == "OK")


# --- Enlaces anulados, caducados o cruzados -----------------------------------


@pytest.mark.asyncio
async def test_a_revoked_employee_invitation_cannot_be_accepted_nor_creates_an_account(
    client: AsyncClient, admin: AdminSession, outbox: InMemoryEmailSender
) -> None:
    """Reinvitar anula el enlace anterior. test_employees.py lo comprueba al VER
    el enlace; aquí, al ACEPTARLO, que es lo que crea la cuenta."""
    employee_id = await add_mechanic(client, admin)
    # El enlace viejo, para un email que no tiene cuenta todavía.
    email = f"viejo-{uuid4().hex[:8]}@example.com"
    old = await invite(client, admin, outbox, employee_id, email)
    await invite(
        client, admin, outbox, employee_id, f"nuevo-{uuid4().hex[:8]}@example.com"
    )

    response = await client.post(f"{old.path}/accept", json={"password": PASSWORD})
    assert response.status_code == 404
    assert response.json() == {"code": "invitation_not_found"}
    assert not await can_sign_in(client, email, PASSWORD)
    assert (await by_name(client, admin, "Juan"))["has_access"] is False


@pytest.mark.asyncio
async def test_an_expired_employee_invitation_cannot_even_be_viewed(
    client: AsyncClient, engines: Engines
) -> None:
    await truncate_all()
    invited = await new_workshop()
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "UPDATE invitations SET expires_at = clock_timestamp() - interval '1s'"
            )
        )
    response = await client.get(invited.path)
    assert response.status_code == 404
    assert response.json() == {"code": "invitation_not_found"}


@pytest.mark.asyncio
async def test_a_link_of_one_kind_does_not_work_on_the_other_route(
    client: AsyncClient,
) -> None:
    """Un token de invitación de empleado no sirve en la ruta de superadministrador
    ni al revés: cada uno se busca solo en su tabla."""
    await truncate_all()
    employee = await new_workshop()
    outbox = InMemoryEmailSender()
    await superadmins.invite(
        email=f"eva-{uuid4().hex[:8]}@example.com",
        invited_by="nadie",
        email_sender=outbox,
    )
    superadmin_token = outbox.sent[-1].body.split("/superadmin-invitations/", 1)[1]
    superadmin_token = superadmin_token.split()[0]

    as_superadmin = await client.post(
        f"/api/v1/superadmin-invitations/{employee.token}/accept",
        json={"password": PASSWORD},
    )
    as_employee = await client.post(
        f"/api/v1/invitations/{employee.workshop_id}/{superadmin_token}/accept",
        json={"password": PASSWORD},
    )
    assert (as_superadmin.status_code, as_employee.status_code) == (404, 404)


@pytest.mark.asyncio
async def test_a_revoked_superadmin_link_cannot_even_be_viewed(
    client: AsyncClient,
) -> None:
    await truncate_all()
    outbox = InMemoryEmailSender()
    email = f"eva-{uuid4().hex[:8]}@example.com"
    for _ in range(2):
        await superadmins.invite(email=email, invited_by="nadie", email_sender=outbox)
    old = outbox.sent[0].body.split("/superadmin-invitations/", 1)[1].split()[0]
    response = await client.get(f"/api/v1/superadmin-invitations/{old}")
    assert response.status_code == 404


# --- Errores que no deben ser un 500 -----------------------------------------


@pytest.mark.asyncio
async def test_the_same_person_on_two_cards_of_one_workshop_is_a_conflict(
    client: AsyncClient, admin: AdminSession, outbox: InMemoryEmailSender
) -> None:
    """UNIQUE (workshop_id, user_id): aceptar con la misma cuenta una segunda
    ficha del mismo taller es un 409 already_an_employee, no un 500, y la
    segunda ficha sigue sin acceso."""
    email = f"pepe-{uuid4().hex[:8]}@example.com"
    first = await invite(
        client, admin, outbox, await add_mechanic(client, admin, "Pepe"), email
    )
    second = await invite(
        client, admin, outbox, await add_mechanic(client, admin, "Pepe bis"), email
    )
    assert await accept(client, first) == 204

    response = await client.post(f"{second.path}/accept", json={"password": PASSWORD})
    assert response.status_code == 409
    assert response.json() == {"code": "already_an_employee"}
    assert (await by_name(client, admin, "Pepe bis"))["has_access"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["name", "role", "active"])
async def test_nulling_a_required_field_of_a_card_is_rejected_not_a_500(
    client: AsyncClient, admin: AdminSession, field: str
) -> None:
    employee_id = await add_mechanic(client, admin)
    version = (await by_name(client, admin, "Juan"))["version"]
    response = await client.patch(
        f"/api/v1/workshop/employees/{employee_id}",
        json={"version": version, field: None},
        headers=admin.headers,
    )
    assert response.status_code == 422, response.text
    juan = await by_name(client, admin, "Juan")
    assert (juan["name"], juan["role"], juan["active"]) == ("Juan", "mechanic", True)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["staff", "superadmin"])
async def test_no_protected_route_answers_its_own_actor_with_a_server_error(
    client: AsyncClient, make_account: MakeAccount, kind: str
) -> None:
    """Complemento de T2: allí, en el prefijo propio, solo se exige "no 403", y
    un 500 lo cumpliría. Con ids inventados y sin cuerpo, cada ruta debe responder
    con un error del cliente (401/403/404/409/422), nunca con uno del servidor."""
    token = await sign_in(client, await make_account(kind))
    headers = {"Authorization": f"Bearer {token}", "X-Workshop-Id": str(uuid4())}
    checked = 0
    for method, path in protected_routes():
        if not path.startswith(ALLOWED_PREFIX[kind]):
            continue
        checked += 1
        response = await client.request(method, path, headers=headers)
        assert response.status_code < 500, (method, path, response.text)
    assert checked >= 5  # prueba de control


# --- El rol sale del taller activo (RNF-03, RNF-09) ---------------------------


@pytest.mark.asyncio
async def test_admin_in_one_workshop_and_mechanic_in_another_has_each_role_in_each(
    client: AsyncClient, outbox: InMemoryEmailSender
) -> None:
    await truncate_all()
    # Ana es administradora de "Talleres Pérez".
    mine = await new_workshop("Talleres Pérez")
    assert await accept(client, mine) == 204
    # Y mecánica en "Taller Norte", invitada por su administrador.
    norte = await new_workshop("Taller Norte")
    assert await accept(client, norte) == 204
    norte_admin = AdminSession(
        norte,
        {**await bearer(client, norte.email), "X-Workshop-Id": norte.workshop_id},
    )
    card = await add_mechanic(client, norte_admin, "Ana en Norte")
    as_mechanic = await invite(client, norte_admin, outbox, card, mine.email)
    assert await accept(client, as_mechanic) == 204

    ana = await bearer(client, mine.email)
    in_mine = await client.get(
        "/api/v1/workshop/employees", headers={**ana, "X-Workshop-Id": mine.workshop_id}
    )
    in_norte = await client.get(
        "/api/v1/workshop/employees",
        headers={**ana, "X-Workshop-Id": norte.workshop_id},
    )
    audit_norte = await client.get(
        "/api/v1/workshop/audit", headers={**ana, "X-Workshop-Id": norte.workshop_id}
    )
    assert in_mine.status_code == 200
    assert (in_norte.status_code, audit_norte.status_code) == (403, 403)


# --- Lo que SuperTokens expone por su cuenta ----------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/api/auth/emailpassword/email/exists", "/api/auth/signup/email/exists"]
)
async def test_nobody_can_ask_whether_an_email_has_an_account(
    client: AsyncClient, make_account: MakeAccount, path: str
) -> None:
    account = await make_account("superadmin")
    known = await client.get(path, params={"email": account.email})
    unknown = await client.get(
        path, params={"email": f"nadie-{uuid4().hex[:8]}@example.com"}
    )
    assert (known.status_code, known.text) == (unknown.status_code, unknown.text)
