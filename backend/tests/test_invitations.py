"""Aceptar invitaciones (RF-04, RF-07) y taller activo validado (A6, T3, T8, RF-113)."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.infra.email import InMemoryEmailSender
from app.platform.workshops import create_workshop
from app.scripts.reset_data import truncate_all
from tests.conftest import Account, Engines, sign_in

MakeAccount = Callable[[str], Awaitable[Account]]
PASSWORD = "contraseña-de-ana-1"


@dataclass(frozen=True)
class Invited:
    workshop_id: str
    email: str
    token: str

    @property
    def path(self) -> str:
        return f"/api/v1/invitations/{self.workshop_id}/{self.token}"


async def new_workshop(
    name: str = "Talleres Pérez", email: str | None = None
) -> Invited:
    """Un taller recién dado de alta, con la invitación de su primer administrador."""
    outbox = InMemoryEmailSender()
    email = email or f"ana-{uuid4().hex[:8]}@example.com"
    created = await create_workshop(
        name=name,
        admin_name="Ana López",
        admin_email=email,
        created_by="test",
        email_sender=outbox,
    )
    link = f"/invitations/{created.workshop_id}/"
    token = outbox.sent[0].body.split(link, 1)[1].split()[0]
    return Invited(str(created.workshop_id), email, token)


@pytest_asyncio.fixture(autouse=True)
async def clean() -> None:
    await truncate_all()


async def accept(
    client: AsyncClient, invited: Invited, password: str = PASSWORD
) -> int:
    response = await client.post(f"{invited.path}/accept", json={"password": password})
    return response.status_code


async def bearer(
    client: AsyncClient, email: str, password: str = PASSWORD
) -> dict[str, str]:
    token = await sign_in(client, Account(email, password, ""))
    return {"Authorization": f"Bearer {token}"}


# --- Ver y aceptar ---------------------------------------------------------


@pytest.mark.asyncio
async def test_the_invitation_shows_who_is_invited_to_what(client: AsyncClient) -> None:
    invited = await new_workshop()
    response = await client.get(invited.path)
    assert response.json() == {
        "workshop_name": "Talleres Pérez",
        "employee_name": "Ana López",
        "email": invited.email,
    }


@pytest.mark.asyncio
async def test_accepting_creates_the_account_and_gives_access(
    client: AsyncClient,
) -> None:
    invited = await new_workshop()
    assert await accept(client, invited) == 204

    headers = await bearer(client, invited.email)
    me = (await client.get("/api/v1/workshop/me", headers=headers)).json()
    assert [w["workshop_id"] for w in me["workshops"]] == [invited.workshop_id]

    active = await client.get(
        "/api/v1/workshop/active",
        headers={**headers, "X-Workshop-Id": invited.workshop_id},
    )
    assert active.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_an_invitation_works_only_once(client: AsyncClient) -> None:
    invited = await new_workshop()
    assert await accept(client, invited) == 204
    assert await accept(client, invited) == 409


@pytest.mark.asyncio
async def test_two_simultaneous_acceptances_give_access_once(
    client: AsyncClient,
) -> None:
    """La invitación se bloquea (FOR UPDATE): la segunda espera y ve la primera."""
    invited = await new_workshop()
    results = await asyncio.gather(accept(client, invited), accept(client, invited))
    assert sorted(results) == [204, 409]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["workshop", "token"])
async def test_a_tampered_link_finds_nothing(client: AsyncClient, change: str) -> None:
    invited = await new_workshop()
    other = await new_workshop("Taller Norte")
    tampered = Invited(
        workshop_id=other.workshop_id if change == "workshop" else invited.workshop_id,
        email=invited.email,
        token="inventado" if change == "token" else invited.token,
    )
    assert (await client.get(tampered.path)).status_code == 404
    assert await accept(client, tampered) == 404


@pytest.mark.asyncio
async def test_an_expired_invitation_finds_nothing(
    client: AsyncClient, engines: Engines
) -> None:
    invited = await new_workshop()
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "UPDATE invitations SET expires_at = clock_timestamp() - interval '1 second'"
            )
        )
    assert await accept(client, invited) == 404


@pytest.mark.asyncio
async def test_someone_already_working_elsewhere_must_prove_it_is_their_account(
    client: AsyncClient,
) -> None:
    """RF-07: si el email ya tiene cuenta, se exige SU contraseña y se le añade el taller."""
    first = await new_workshop("Talleres Pérez")
    assert await accept(client, first) == 204
    second = await new_workshop("Taller Norte", email=first.email)

    assert await accept(client, second, password="otra-contraseña-9") == 403
    assert await accept(client, second) == 204

    me = (
        await client.get(
            "/api/v1/workshop/me", headers=await bearer(client, first.email)
        )
    ).json()
    assert {w["workshop_name"] for w in me["workshops"]} == {
        "Talleres Pérez",
        "Taller Norte",
    }


@pytest.mark.asyncio
async def test_a_superadmin_cannot_become_an_employee(
    client: AsyncClient, make_account: MakeAccount
) -> None:
    superadmin = await make_account("superadmin")
    invited = await new_workshop(email=superadmin.email)
    response = await client.post(
        f"{invited.path}/accept", json={"password": superadmin.password}
    )
    assert response.json() == {"code": "superadmin_cannot_be_employee"}


@pytest.mark.asyncio
async def test_a_half_created_account_is_recovered_by_accepting_again(
    client: AsyncClient, make_account: MakeAccount
) -> None:
    """Si la aceptación falló después de crear la cuenta de SuperTokens, queda
    sin fila en users (no puede iniciar sesión); aceptar de nuevo la recupera."""
    orphan = await make_account("orphan")
    invited = await new_workshop(email=orphan.email)
    response = await client.post(
        f"{invited.path}/accept", json={"password": orphan.password}
    )
    assert response.status_code == 204
    assert await sign_in(client, orphan)


@pytest.mark.asyncio
async def test_the_access_limit_is_checked_before_creating_any_account(
    client: AsyncClient, engines: Engines
) -> None:
    invited = await new_workshop()
    assert await accept(client, invited) == 204
    # Un segundo empleado invitado, con el límite del taller en 1.
    second_email = f"luis-{uuid4().hex[:8]}@example.com"
    token = "token-del-segundo-empleado"
    from app.core.tokens import hash_token

    async with engines.platform.begin() as conn:
        employee_id = await conn.scalar(
            text(
                "INSERT INTO employees (workshop_id, name, role)"
                " VALUES (:w, 'Luis', 'mechanic') RETURNING id"
            ),
            {"w": invited.workshop_id},
        )
        await conn.execute(
            text(
                "INSERT INTO invitations (workshop_id, employee_id, email, token_hash, expires_at)"
                " VALUES (:w, :e, :m, :h, clock_timestamp() + interval '1 day')"
            ),
            {
                "w": invited.workshop_id,
                "e": employee_id,
                "m": second_email,
                "h": hash_token(token),
            },
        )
        await conn.execute(
            text("UPDATE workshops SET max_employees_with_access = 1 WHERE id = :w"),
            {"w": invited.workshop_id},
        )
    second = Invited(invited.workshop_id, second_email, token)
    response = await client.post(f"{second.path}/accept", json={"password": PASSWORD})
    assert response.json() == {"code": "employee_limit_reached"}
    # Y no se creó ninguna cuenta: iniciar sesión con ese email no funciona.
    signin = await client.post(
        "/api/auth/signin",
        headers={"st-auth-mode": "header"},
        json={
            "formFields": [
                {"id": "email", "value": second_email},
                {"id": "password", "value": PASSWORD},
            ]
        },
    )
    assert signin.json()["status"] == "WRONG_CREDENTIALS_ERROR"


# --- Taller activo validado ----------------------------------------------


@pytest.mark.asyncio
async def test_t3_a_workshop_you_do_not_work_in_is_404(client: AsyncClient) -> None:
    mine = await new_workshop("Talleres Pérez")
    theirs = await new_workshop("Taller Norte")
    assert await accept(client, mine) == 204
    headers = await bearer(client, mine.email)
    response = await client.get(
        "/api/v1/workshop/active",
        headers={**headers, "X-Workshop-Id": theirs.workshop_id},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_t8_deactivating_an_employee_cuts_access_on_the_next_request(
    client: AsyncClient, engines: Engines
) -> None:
    """RF-06: con la sesión abierta, sin cerrarla, y sin afectar a sus otros talleres."""
    first = await new_workshop("Talleres Pérez")
    second = await new_workshop("Taller Norte", email=first.email)
    assert await accept(client, first) == 204
    assert await accept(client, second) == 204
    headers = await bearer(client, first.email)

    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE employees SET active = false WHERE workshop_id = :w"),
            {"w": first.workshop_id},
        )

    in_first = await client.get(
        "/api/v1/workshop/active",
        headers={**headers, "X-Workshop-Id": first.workshop_id},
    )
    in_second = await client.get(
        "/api/v1/workshop/active",
        headers={**headers, "X-Workshop-Id": second.workshop_id},
    )
    assert in_first.status_code == 404
    assert in_second.status_code == 200


@pytest.mark.asyncio
async def test_a_deactivated_workshop_cuts_access_and_its_invitations(
    client: AsyncClient, engines: Engines
) -> None:
    """RF-113: desactivar un taller corta el acceso sin borrar nada."""
    invited = await new_workshop()
    assert await accept(client, invited) == 204
    headers = {
        **await bearer(client, invited.email),
        "X-Workshop-Id": invited.workshop_id,
    }
    pending = await new_workshop("Taller Norte")

    async with engines.platform.begin() as conn:
        await conn.execute(text("UPDATE workshops SET status = 'inactive'"))

    assert (
        await client.get("/api/v1/workshop/active", headers=headers)
    ).status_code == 404
    me = (await client.get("/api/v1/workshop/me", headers=headers)).json()
    assert me["workshops"] == []
    assert await accept(client, pending) == 404


@pytest.mark.asyncio
async def test_without_the_workshop_header_the_request_is_rejected(
    client: AsyncClient,
) -> None:
    invited = await new_workshop()
    assert await accept(client, invited) == 204
    headers = await bearer(client, invited.email)
    assert (
        await client.get("/api/v1/workshop/active", headers=headers)
    ).status_code == 422
