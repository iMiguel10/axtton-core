"""Cuenta del personal: recuperar y cambiar la contraseña, sesiones (RF-120 a RF-123).

Para comprobar que una sesión se cerró se usa su token de RENOVACIÓN: el de
acceso sigue valiendo hasta caducar (5 minutos) porque se valida sin consultar
al core; lo que se corta al cerrar una sesión es la renovación.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.infra.email import InMemoryEmailSender, current_email_sender, set_email_sender
from tests.conftest import Account

MakeAccount = Callable[[str], Awaitable[Account]]
NEW_PASSWORD = "otra-contraseña-larga-2"


@dataclass(frozen=True)
class Tokens:
    access: str
    refresh: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access}"}


@pytest_asyncio.fixture(autouse=True)
async def outbox() -> AsyncIterator[InMemoryEmailSender]:
    """Sustituye el emisor del proceso: lo usan también los emails de SuperTokens."""
    previous = current_email_sender()
    sender = InMemoryEmailSender()
    set_email_sender(sender)
    yield sender
    set_email_sender(previous)


def form(**fields: str) -> dict[str, list[dict[str, str]]]:
    return {"formFields": [{"id": k, "value": v} for k, v in fields.items()]}


async def login(client: AsyncClient, email: str, password: str) -> Tokens | None:
    response = await client.post(
        "/api/auth/signin",
        headers={"st-auth-mode": "header"},
        json=form(email=email, password=password),
    )
    if response.json()["status"] != "OK":
        return None
    return Tokens(
        response.headers["st-access-token"], response.headers["st-refresh-token"]
    )


async def can_refresh(client: AsyncClient, tokens: Tokens) -> bool:
    response = await client.post(
        "/api/auth/session/refresh",
        headers={"st-auth-mode": "header", "Authorization": f"Bearer {tokens.refresh}"},
    )
    return response.status_code == 200


# --- Recuperar la contraseña (RF-121) ---------------------------------------


@pytest.mark.asyncio
async def test_reset_answers_the_same_for_unknown_emails_and_sends_nothing(
    client: AsyncClient, make_account: MakeAccount, outbox: InMemoryEmailSender
) -> None:
    staff = await make_account("staff")
    known = await client.post(
        "/api/auth/user/password/reset/token", json=form(email=staff.email)
    )
    unknown = await client.post(
        "/api/auth/user/password/reset/token",
        json=form(email=f"nadie-{uuid4().hex}@example.com"),
    )
    # La misma respuesta: no revela qué emails tienen cuenta.
    assert known.json() == unknown.json() == {"status": "OK"}
    assert [email.to for email in outbox.sent] == [staff.email]


@pytest.mark.asyncio
async def test_resetting_the_password_closes_every_open_session(
    client: AsyncClient, make_account: MakeAccount, outbox: InMemoryEmailSender
) -> None:
    staff = await make_account("staff")
    old_session = await login(client, staff.email, staff.password)
    assert old_session and await can_refresh(client, old_session)

    await client.post(
        "/api/auth/user/password/reset/token", json=form(email=staff.email)
    )
    [email] = outbox.sent
    # El enlace va a la página del frontend y sale por nuestro SMTP, no por SuperTokens.
    link = next(word for word in email.body.split() if word.startswith("http"))
    assert urlparse(link).path == "/reset-password"
    token = parse_qs(urlparse(link).query)["token"][0]

    reset = await client.post(
        "/api/auth/user/password/reset",
        json={**form(password=NEW_PASSWORD), "token": token},
    )
    assert reset.json()["status"] == "OK"

    assert not await can_refresh(client, old_session)
    assert await login(client, staff.email, staff.password) is None
    assert await login(client, staff.email, NEW_PASSWORD) is not None


# --- Cambiar la contraseña (RF-122) y sesiones (RF-123) ---------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["staff", "superadmin"])
async def test_changing_the_password_requires_the_current_one(
    client: AsyncClient, make_account: MakeAccount, kind: str
) -> None:
    account = await make_account(kind)
    tokens = await login(client, account.email, account.password)
    assert tokens
    prefix = "workshop" if kind == "staff" else "admin"
    response = await client.post(
        f"/api/v1/{prefix}/account/password",
        json={"current_password": "no-es-la-mía-123", "new_password": NEW_PASSWORD},
        headers=tokens.headers,
    )
    assert response.json() == {"code": "wrong_password"}


@pytest.mark.asyncio
async def test_a_weak_new_password_is_rejected(
    client: AsyncClient, make_account: MakeAccount
) -> None:
    staff = await make_account("staff")
    tokens = await login(client, staff.email, staff.password)
    assert tokens
    response = await client.post(
        "/api/v1/workshop/account/password",
        # 10 caracteres pero sin números: la política de SuperTokens lo rechaza.
        json={"current_password": staff.password, "new_password": "soloLetras"},
        headers=tokens.headers,
    )
    assert response.json() == {"code": "weak_password"}


@pytest.mark.asyncio
async def test_changing_the_password_keeps_this_session_and_closes_the_others(
    client: AsyncClient, make_account: MakeAccount
) -> None:
    staff = await make_account("staff")
    here = await login(client, staff.email, staff.password)
    elsewhere = await login(client, staff.email, staff.password)
    assert here and elsewhere

    response = await client.post(
        "/api/v1/workshop/account/password",
        json={"current_password": staff.password, "new_password": NEW_PASSWORD},
        headers=here.headers,
    )
    assert response.status_code == 204
    assert await can_refresh(client, here)
    assert not await can_refresh(client, elsewhere)


@pytest.mark.asyncio
async def test_sessions_are_listed_and_the_others_can_be_closed(
    client: AsyncClient, make_account: MakeAccount
) -> None:
    staff = await make_account("staff")
    here = await login(client, staff.email, staff.password)
    elsewhere = await login(client, staff.email, staff.password)
    assert here and elsewhere

    listed = (
        await client.get("/api/v1/workshop/account/sessions", headers=here.headers)
    ).json()
    assert sorted(s["current"] for s in listed) == [False, True]

    closed = await client.post(
        "/api/v1/workshop/account/sessions/revoke-others", headers=here.headers
    )
    assert closed.status_code == 204
    assert not await can_refresh(client, elsewhere)
    listed = (
        await client.get("/api/v1/workshop/account/sessions", headers=here.headers)
    ).json()
    assert [s["current"] for s in listed] == [True]
