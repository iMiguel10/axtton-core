"""La sesión del cliente en el portal (F4 paso 2, T7, RF-47).

Para ver que una sesión se cerró de verdad se usa su token de renovación: el de
acceso se valida sin consultar al core. La cerradura (`portal_epoch`) es lo que
corta el token de acceso al instante, y lo comprueba `/portal/me`.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy import text
from supertokens_python.asyncio import list_users_by_account_info
from supertokens_python.recipe.passwordless.asyncio import signinup
from supertokens_python.recipe.session.asyncio import (
    create_new_session_without_request_response,
)
from supertokens_python.types.base import AccountInfoInput

from app.core import sessions
from app.core.db import workshop_transaction
from app.domain.portal import SESSION_LIFETIME
from app.infra.email import InMemoryEmailSender
from app.scripts.reset_data import truncate_all
from app.services import clients as client_service
from app.services import portal_auth as portal_auth_service
from tests.conftest import Account, Engines, sign_in
from tests.test_clients import AdminSession, create, open_workshop
from tests.test_portal_auth import (
    bearer,
    claims,
    consume,
    link_for,
    me,
    new_email,
    outbox,
)

__all__ = ["outbox"]

MakeAccount = Callable[[str], Awaitable[Account]]
CLIENTS = "/api/v1/workshop/clients"


@dataclass(frozen=True)
class Shops:
    a: AdminSession
    b: AdminSession

    @property
    def id_a(self) -> UUID:
        return UUID(self.a.invited.workshop_id)

    @property
    def id_b(self) -> UUID:
        return UUID(self.b.invited.workshop_id)


@pytest_asyncio.fixture
async def shops(client: AsyncClient) -> Shops:
    await truncate_all()
    return Shops(
        await open_workshop(client, "Taller A"), await open_workshop(client, "Taller B")
    )


async def can_refresh(client: AsyncClient, session: Response) -> bool:
    response = await client.post(
        "/api/auth/session/refresh",
        headers={
            "st-auth-mode": "header",
            "Authorization": f"Bearer {session.headers['st-refresh-token']}",
        },
    )
    return response.status_code == 200


async def enter(
    client: AsyncClient, outbox: InMemoryEmailSender, workshop_id: UUID, email: str
) -> Response:
    session = await consume(client, *await link_for(client, outbox, workshop_id, email))
    assert session.status_code == 204, session.text
    return session


async def patch_client(
    client: AsyncClient, admin: AdminSession, target: dict[str, Any], **changes: Any
) -> None:
    response = await client.patch(
        f"{CLIENTS}/{target['id']}",
        json={"version": target["version"], **changes},
        headers=admin.headers,
    )
    assert response.status_code == 204, response.text


async def assert_ended(client: AsyncClient, session: Response) -> None:
    response = await me(client, session)
    assert response.status_code == 401
    assert response.json() == {"code": "portal_session_ended"}


# --- T7: se cierran las de ese taller, y solo esas ------------------------------


@pytest.mark.asyncio
async def test_t7_anonymizing_in_a_workshop_leaves_the_other_one_alive(
    client: AsyncClient, shops: Shops, outbox: InMemoryEmailSender
) -> None:
    """El mismo email es cliente de A y de B: un solo usuario de SuperTokens y dos
    sesiones. `revokeAllSessionsForUser` cerraría también la de B."""
    email = new_email()
    in_a = await create(client, shops.a.headers, email=email)
    await create(client, shops.b.headers, email=email)
    session_a = await enter(client, outbox, shops.id_a, email)
    session_b = await enter(client, outbox, shops.id_b, email)
    assert claims(session_a)["sub"] == claims(session_b)["sub"]

    response = await client.post(
        f"{CLIENTS}/{in_a['id']}/anonymize",
        json={"version": in_a["version"]},
        headers=shops.a.headers,
    )
    assert response.status_code == 204, response.text

    # La de A: ni el token de acceso, que aún no ha caducado, ni la renovación.
    assert not await can_refresh(client, session_a)
    await assert_ended(client, session_a)
    # La de B sigue viva, y el usuario existe: se puede volver a entrar en B.
    assert (await me(client, session_b)).json()["workshop_name"] == "Taller B"
    assert await can_refresh(client, session_b)
    await enter(client, outbox, shops.id_b, email)


@pytest.mark.asyncio
async def test_t7_changing_the_email_in_a_workshop_leaves_the_other_one_alive(
    client: AsyncClient, shops: Shops, outbox: InMemoryEmailSender
) -> None:
    email, corrected = new_email(), new_email()
    in_a = await create(client, shops.a.headers, email=email)
    await create(client, shops.b.headers, email=email)
    session_a = await enter(client, outbox, shops.id_a, email)
    session_b = await enter(client, outbox, shops.id_b, email)

    await patch_client(client, shops.a, in_a, email=corrected)

    assert not await can_refresh(client, session_a)
    await assert_ended(client, session_a)
    assert (await me(client, session_b)).status_code == 200
    assert await can_refresh(client, session_b)
    # Quien tiene el email corregido entra, con otro usuario de SuperTokens.
    session_new = await enter(client, outbox, shops.id_a, corrected)
    assert claims(session_new)["sub"] != claims(session_a)["sub"]
    assert (await me(client, session_new)).status_code == 200


@pytest.mark.asyncio
async def test_two_clients_of_a_workshop_do_not_touch_each_other(
    client: AsyncClient, shops: Shops, outbox: InMemoryEmailSender
) -> None:
    one, other = new_email(), new_email()
    first = await create(client, shops.a.headers, email=one)
    await create(client, shops.a.headers, email=other, phone="611")
    session_one = await enter(client, outbox, shops.id_a, one)
    session_other = await enter(client, outbox, shops.id_a, other)

    await patch_client(client, shops.a, first, email=new_email())

    await assert_ended(client, session_one)
    assert (await me(client, session_other)).status_code == 200
    assert await can_refresh(client, session_other)


@pytest.mark.asyncio
async def test_closing_a_client_never_touches_the_staff_account_of_that_email(
    client: AsyncClient,
    shops: Shops,
    outbox: InMemoryEmailSender,
    make_account: MakeAccount,
) -> None:
    """Ana es personal y clienta con el mismo email: son dos usuarios."""
    staff = await make_account("staff")
    in_a = await create(client, shops.a.headers, email=staff.email)
    client_session = await enter(client, outbox, shops.id_a, staff.email)
    login = await client.post(
        "/api/auth/signin",
        headers={"st-auth-mode": "header"},
        json={
            "formFields": [
                {"id": "email", "value": staff.email},
                {"id": "password", "value": staff.password},
            ]
        },
    )
    assert login.json()["status"] == "OK"

    await patch_client(client, shops.a, in_a, email=new_email())

    assert not await can_refresh(client, client_session)
    assert await can_refresh(client, login)
    token = await sign_in(client, staff)
    staff_me = await client.get(
        "/api/v1/workshop/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert staff_me.json()["actor"] == "staff"


@pytest.mark.asyncio
async def test_editing_anything_else_does_not_end_the_session(
    client: AsyncClient, shops: Shops, outbox: InMemoryEmailSender
) -> None:
    email = new_email()
    in_a = await create(client, shops.a.headers, email=email)
    session = await enter(client, outbox, shops.id_a, email)

    # Mandar el mismo email tampoco es cambiarlo.
    await patch_client(client, shops.a, in_a, name="Otro nombre", email=email.upper())

    assert (await me(client, session)).json()["client_name"] == "Otro nombre"
    assert await can_refresh(client, session)


@pytest.mark.asyncio
async def test_giving_an_email_to_a_client_without_one_closes_nothing(
    client: AsyncClient, shops: Shops, outbox: InMemoryEmailSender
) -> None:
    in_a = await create(client, shops.a.headers)
    email = new_email()
    await patch_client(client, shops.a, in_a, email=email)
    assert (await me(client, await enter(client, outbox, shops.id_a, email))).is_success


# --- RF-15, RNF-40: el email tampoco se queda en SuperTokens ------------------------


async def passwordless_users(email: str) -> list[str]:
    users = await list_users_by_account_info("public", AccountInfoInput(email=email))
    return [
        user.id
        for user in users
        if any(m.recipe_id == "passwordless" for m in user.login_methods)
    ]


@pytest.mark.asyncio
async def test_rnf40_anonymizing_the_last_session_removes_the_email_from_supertokens(
    client: AsyncClient, shops: Shops, outbox: InMemoryEmailSender
) -> None:
    """El barrido de test_anonymize.py solo mira nuestra base de datos: el usuario
    passwordless es lo único que guarda el email en la de SuperTokens."""
    email = new_email()
    in_a = await create(client, shops.a.headers, email=email)
    await enter(client, outbox, shops.id_a, email)
    assert await passwordless_users(email)

    response = await client.post(
        f"{CLIENTS}/{in_a['id']}/anonymize",
        json={"version": in_a["version"]},
        headers=shops.a.headers,
    )
    assert response.status_code == 204, response.text
    assert await passwordless_users(email) == []


@pytest.mark.asyncio
async def test_the_user_stays_while_another_workshop_has_a_session(
    client: AsyncClient, shops: Shops, outbox: InMemoryEmailSender
) -> None:
    email = new_email()
    in_a = await create(client, shops.a.headers, email=email)
    await create(client, shops.b.headers, email=email)
    await enter(client, outbox, shops.id_a, email)
    session_b = await enter(client, outbox, shops.id_b, email)

    await patch_client(client, shops.a, in_a, email=new_email())

    assert await passwordless_users(email) == [claims(session_b)["sub"]]
    assert (await me(client, session_b)).status_code == 200


@pytest.mark.asyncio
async def test_a_client_of_another_workshop_can_enter_after_the_user_is_removed(
    client: AsyncClient, shops: Shops, outbox: InMemoryEmailSender
) -> None:
    """Sin sesión en B, cerrar A borra el usuario. Sigue siendo cliente de B: al
    entrar, `signinup` crea otro, y nada nuestro guardaba el id del anterior."""
    email = new_email()
    in_a = await create(client, shops.a.headers, email=email)
    await create(client, shops.b.headers, email=email)
    session_a = await enter(client, outbox, shops.id_a, email)

    await patch_client(client, shops.a, in_a, email=new_email())
    assert await passwordless_users(email) == []

    session_b = await enter(client, outbox, shops.id_b, email)
    assert claims(session_b)["sub"] != claims(session_a)["sub"]
    assert (await me(client, session_b)).json()["workshop_name"] == "Taller B"


# --- La cerradura: al instante, y también para lo que llega tarde -----------------


@pytest.mark.asyncio
async def test_a_session_created_after_the_email_changed_is_useless(
    client: AsyncClient, shops: Shops, outbox: InMemoryEmailSender
) -> None:
    """La carrera: consumir el enlace confirma, el taller cambia el email y cierra
    las sesiones, y solo entonces se crea esta. Revocar no la alcanzó (aún no
    existía); la cerradura, sí. Sin ella, seguiría entrando con el email viejo."""
    email = new_email()
    in_a = await create(client, shops.a.headers, email=email)
    _, token = await link_for(client, outbox, shops.id_a, email)

    login = await portal_auth_service.consume(shops.id_a, token)
    await patch_client(client, shops.a, in_a, email=new_email())
    user = await signinup("public", email=email, phone_number=None)
    late = await create_new_session_without_request_response(
        "public",
        user.user.login_methods[0].recipe_user_id,
        user_context={sessions.PORTAL_LOGIN: login},
    )

    response = await client.get(
        "/api/v1/portal/me",
        headers={"Authorization": f"Bearer {late.get_access_token()}"},
    )
    assert response.status_code == 401
    assert response.json() == {"code": "portal_session_ended"}


@pytest.mark.asyncio
async def test_a_session_that_no_longer_works_is_closed_for_good(
    client: AsyncClient, shops: Shops, outbox: InMemoryEmailSender, engines: Engines
) -> None:
    """Aunque cerrarla en segundo plano fallara, la primera petición la cierra. Si
    no, el 401 haría al navegador renovarla y volver aquí en bucle."""
    email = new_email()
    in_a = await create(client, shops.a.headers, email=email)
    session = await enter(client, outbox, shops.id_a, email)
    # La cerradura cambia sin pasar por el endpoint, que es quien cierra.
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE clients SET portal_epoch = portal_epoch + 1 WHERE id = :c"),
            {"c": in_a["id"]},
        )
    await assert_ended(client, session)
    assert not await can_refresh(client, session)


# --- Pasar por el taller no borra lo que debe volver -------------------------------


@pytest.mark.asyncio
async def test_archiving_suspends_access_and_unarchiving_gives_it_back(
    client: AsyncClient, shops: Shops, outbox: InMemoryEmailSender
) -> None:
    """Archivar no cambia de quién es la sesión: ahora no entra (403), y al
    desarchivar vuelve a entrar con la misma."""
    email = new_email()
    in_a = await create(client, shops.a.headers, email=email)
    session = await enter(client, outbox, shops.id_a, email)
    archive = await client.post(
        f"{CLIENTS}/{in_a['id']}/archive",
        json={"version": in_a["version"]},
        headers=shops.a.headers,
    )
    assert archive.status_code == 204

    refused = await me(client, session)
    assert refused.status_code == 403
    assert refused.json() == {"code": "portal_access_revoked"}

    unarchive = await client.post(
        f"{CLIENTS}/{in_a['id']}/unarchive",
        json={"version": in_a["version"] + 1},
        headers=shops.a.headers,
    )
    assert unarchive.status_code == 204
    assert (await me(client, session)).status_code == 200


# --- RF-47: 30 días, y el cliente puede cerrarla -----------------------------------


@pytest.mark.asyncio
async def test_rf47_the_session_says_it_lasts_thirty_days(
    client: AsyncClient, shops: Shops, outbox: InMemoryEmailSender
) -> None:
    email = new_email()
    await create(client, shops.a.headers, email=email)
    session = await enter(client, outbox, shops.id_a, email)
    expires = claims(session)["portal_expires_at"]
    assert isinstance(expires, int)
    expected = datetime.now(UTC) + timedelta(days=30)
    assert SESSION_LIFETIME == timedelta(days=30)
    assert expires == pytest.approx(expected.timestamp(), abs=30)


@pytest.mark.asyncio
async def test_rf47_a_session_past_its_thirty_days_is_over_and_closed(
    client: AsyncClient,
    shops: Shops,
    outbox: InMemoryEmailSender,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = new_email()
    await create(client, shops.a.headers, email=email)
    monkeypatch.setattr(sessions, "SESSION_LIFETIME", timedelta(seconds=-1))
    session = await enter(client, outbox, shops.id_a, email)

    await assert_ended(client, session)
    assert not await can_refresh(client, session)


@pytest.mark.asyncio
async def test_rf47_the_client_can_sign_out(
    client: AsyncClient, shops: Shops, outbox: InMemoryEmailSender
) -> None:
    email = new_email()
    await create(client, shops.a.headers, email=email)
    session = await enter(client, outbox, shops.id_a, email)
    response = await client.post(
        "/api/auth/signout", headers={"st-auth-mode": "header", **bearer(session)}
    )
    assert response.json()["status"] == "OK"
    assert not await can_refresh(client, session)


@pytest.mark.asyncio
async def test_the_service_returns_the_previous_email_only_when_it_changes(
    client: AsyncClient, shops: Shops
) -> None:
    email, other = new_email(), new_email()
    in_a = await create(client, shops.a.headers, email=email)
    async with workshop_transaction([shops.id_a]) as session:
        unchanged = await client_service.update_client(
            session,
            UUID(in_a["id"]),
            expected_version=in_a["version"],
            changes={"name": "Otro"},
        )
    async with workshop_transaction([shops.id_a]) as session:
        changed = await client_service.update_client(
            session,
            UUID(in_a["id"]),
            expected_version=in_a["version"] + 1,
            changes={"email": other},
        )
    assert (unchanged, changed) == (None, email)
