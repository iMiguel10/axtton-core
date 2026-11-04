"""Entrar en el portal con un enlace mágico (F4 paso 1, arquitectura §7.2).

T5 (cambiar el taller de la URL), T6 (un solo uso) y T10 (siempre una sesión de
cliente del taller del enlace), más RF-40, RF-41 y RF-45. Contra el core real de
SuperTokens y Postgres con RLS: el enlace de otro taller no se encuentra porque
RLS no lo deja ver, no porque el código lo compruebe.
"""

import asyncio
import base64
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.deps import get_email_sender
from app.core.tokens import hash_token
from app.infra.email import DisabledEmailSender, Email, InMemoryEmailSender
from app.main import app
from app.repositories import portal_links as link_repo
from app.services import clients as client_service
from app.services import portal_auth as portal_auth_service
from app.services.portal_auth import PortalLinkInvalidError
from tests.conftest import Account, Engines, TwoWorkshops, sign_in
from tests.test_concurrency import (  # noqa: F401 (dispose_global_engines es autouse)
    GRACE,
    dispose_global_engines,
    finish,
    open_transaction,
)

MakeAccount = Callable[[str], Awaitable[Account]]
LINK = re.compile(r"/portal/access/([0-9a-f-]{36})#([A-Za-z0-9_-]+)")


@pytest_asyncio.fixture
async def outbox() -> AsyncIterator[InMemoryEmailSender]:
    sender = InMemoryEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    yield sender
    app.dependency_overrides.pop(get_email_sender, None)


def new_email() -> str:
    return f"cliente-{uuid4().hex[:10]}@example.com"


async def add_client(
    engines: Engines, workshop_id: UUID, email: str | None, name: str = "Ana Ruiz"
) -> UUID:
    async with engines.platform.begin() as conn:
        client_id = await conn.scalar(
            text(
                "INSERT INTO clients (workshop_id, name, phone, email)"
                " VALUES (:w, :n, '600111222', :e) RETURNING id"
            ),
            {"w": workshop_id, "n": name, "e": email},
        )
    assert isinstance(client_id, UUID)
    return client_id


async def request_link(client: AsyncClient, workshop_id: UUID, email: str) -> Response:
    return await client.post(
        "/api/v1/portal/auth/request-link",
        json={"workshop_id": str(workshop_id), "email": email},
    )


def links_in(email: Email) -> list[tuple[UUID, str]]:
    return [(UUID(w), token) for w, token in LINK.findall(email.body)]


async def link_for(
    client: AsyncClient, outbox: InMemoryEmailSender, workshop_id: UUID, email: str
) -> tuple[UUID, str]:
    """Pide el enlace en la entrada del taller y devuelve el único que llega."""
    await request_link(client, workshop_id, email)
    [link] = links_in(outbox.sent[-1])
    return link


async def consume(client: AsyncClient, workshop_id: UUID, token: str) -> Response:
    # Modo cabecera: los tokens llegan en la respuesta, no en cookies.
    return await client.post(
        "/api/v1/portal/auth/consume",
        headers={"st-auth-mode": "header"},
        json={"workshop_id": str(workshop_id), "token": token},
    )


def bearer(response: Response) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.headers['st-access-token']}"}


def claims(response: Response) -> dict[str, object]:
    payload = response.headers["st-access-token"].split(".")[1]
    decoded: dict[str, object] = json.loads(
        base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    )
    return decoded


async def me(client: AsyncClient, response: Response) -> Response:
    return await client.get("/api/v1/portal/me", headers=bearer(response))


async def enter_portal(
    client: AsyncClient, engines: Engines, workshop_id: UUID
) -> dict[str, str]:
    """Un cliente nuevo del taller que entra en el portal: su cabecera Bearer.

    Para las pruebas de otros ficheros (T2, y las del portal en los pasos
    siguientes): pasa por el mismo camino que un cliente de verdad.
    """
    sender = InMemoryEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    try:
        email = new_email()
        await add_client(engines, workshop_id, email)
        session = await consume(
            client, *await link_for(client, sender, workshop_id, email)
        )
    finally:
        app.dependency_overrides.pop(get_email_sender, None)
    assert session.status_code == 204, session.text
    return bearer(session)


# --- La página de entrada de cada taller ---------------------------------------


@pytest.mark.asyncio
async def test_the_entry_page_shows_the_workshop_name(
    client: AsyncClient, engines: Engines, two_workshops: TwoWorkshops
) -> None:
    response = await client.get(f"/api/v1/portal/workshops/{two_workshops.a}")
    assert response.status_code == 200
    assert response.json() == {"workshop_name": "Taller A"}

    # Uno que no existe y uno desactivado (RF-113) responden igual.
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE workshops SET status = 'inactive' WHERE id = :w"),
            {"w": two_workshops.b},
        )
    for workshop_id in (uuid4(), two_workshops.b):
        missing = await client.get(f"/api/v1/portal/workshops/{workshop_id}")
        assert missing.status_code == 404
        assert missing.json() == {"code": "workshop_not_found"}


# --- Pedir y consumir --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_client_gets_a_link_and_enters_their_workshop(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    outbox: InMemoryEmailSender,
) -> None:
    email = new_email()
    await add_client(engines, two_workshops.a, email)

    response = await request_link(client, two_workshops.a, email.upper())
    assert response.status_code == 202
    [sent] = outbox.sent
    assert sent.to == email
    assert sent.sender_name == "Taller A (AXTTON CORE)"
    assert sent.subject == "Tu acceso al portal de Taller A"
    [(workshop_id, token)] = links_in(sent)
    assert workshop_id == two_workshops.a

    session = await consume(client, workshop_id, token)
    assert session.status_code == 204
    profile = await me(client, session)
    assert profile.status_code == 200
    assert profile.json() == {
        "actor": "client",
        "workshop_id": str(two_workshops.a),
        "workshop_name": "Taller A",
        "timezone": "Europe/Madrid",
        "client_name": "Ana Ruiz",
        "language": "es",
    }


@pytest.mark.asyncio
async def test_rf45_a_client_of_two_workshops_enters_each_from_its_page(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    outbox: InMemoryEmailSender,
) -> None:
    """Desde la entrada de A llega solo el enlace de A, y desde la de B, solo el
    de B. Usar uno no gasta el otro: con los códigos de SuperTokens, consumir uno
    borraba los demás del mismo email (decisión 0006)."""
    email = new_email()
    client_a = await add_client(engines, two_workshops.a, email)
    client_b = await add_client(engines, two_workshops.b, email, name="Ana R.")

    link_a = await link_for(client, outbox, two_workshops.a, email)
    link_b = await link_for(client, outbox, two_workshops.b, email)
    assert (link_a[0], link_b[0]) == (two_workshops.a, two_workshops.b)
    assert [sent.sender_name for sent in outbox.sent] == [
        "Taller A (AXTTON CORE)",
        "Taller B (AXTTON CORE)",
    ]

    in_a = await consume(client, *link_a)
    in_b = await consume(client, *link_b)
    assert (in_a.status_code, in_b.status_code) == (204, 204)
    assert claims(in_a)["workshop_id"] == str(two_workshops.a)
    assert claims(in_a)["client_id"] == str(client_a)
    assert claims(in_b)["workshop_id"] == str(two_workshops.b)
    assert claims(in_b)["client_id"] == str(client_b)
    # Un solo usuario de SuperTokens para el email; dos sesiones, una por taller.
    assert claims(in_a)["sub"] == claims(in_b)["sub"]
    assert (await me(client, in_a)).json()["workshop_name"] == "Taller A"
    assert (await me(client, in_b)).json()["workshop_name"] == "Taller B"


@pytest.mark.asyncio
async def test_rf41_the_answer_is_the_same_whether_or_not_the_client_exists(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    outbox: InMemoryEmailSender,
) -> None:
    known, archived, of_b, deactivated = (new_email() for _ in range(4))
    await add_client(engines, two_workshops.a, known)
    archived_id = await add_client(engines, two_workshops.a, archived)
    await add_client(engines, two_workshops.b, of_b)
    await add_client(engines, two_workshops.b, deactivated)
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE clients SET archived_at = clock_timestamp() WHERE id = :c"),
            {"c": archived_id},
        )

    answers = [
        await request_link(client, two_workshops.a, known),
        await request_link(client, two_workshops.a, new_email()),
        await request_link(client, two_workshops.a, archived),
        # Cliente de B, pedido en la entrada de A: no sale nada, ni de B.
        await request_link(client, two_workshops.a, of_b),
        # Un taller que no existe.
        await request_link(client, uuid4(), known),
    ]
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE workshops SET status = 'inactive' WHERE id = :w"),
            {"w": two_workshops.b},
        )
    # Un taller desactivado (RF-113).
    answers.append(await request_link(client, two_workshops.b, deactivated))

    assert {(r.status_code, r.content) for r in answers} == {(202, b"null")}
    assert [sent.to for sent in outbox.sent] == [known]


@pytest.mark.asyncio
async def test_without_smtp_no_link_is_issued(
    client: AsyncClient, engines: Engines, two_workshops: TwoWorkshops
) -> None:
    email = new_email()
    await add_client(engines, two_workshops.a, email)
    app.dependency_overrides[get_email_sender] = DisabledEmailSender
    try:
        response = await request_link(client, two_workshops.a, email)
        assert response.status_code == 202
    finally:
        app.dependency_overrides.pop(get_email_sender, None)
    async with engines.platform.begin() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM portal_links")) == 0


@pytest.mark.asyncio
async def test_only_the_hash_of_the_link_is_stored(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    outbox: InMemoryEmailSender,
) -> None:
    email = new_email()
    await add_client(engines, two_workshops.a, email)
    _, token = await link_for(client, outbox, two_workshops.a, email)
    async with engines.platform.begin() as conn:
        stored = await conn.scalar(text("SELECT token_hash FROM portal_links"))
        lifetime = await conn.scalar(
            text("SELECT expires_at - created_at FROM portal_links")
        )
    assert stored == hash_token(token)
    assert lifetime.total_seconds() == pytest.approx(15 * 60, abs=5)


# --- T5, T6: el enlace es de su taller y vale una vez ------------------------


@pytest.mark.asyncio
async def test_t5_a_link_with_another_workshop_in_the_url_opens_nothing(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    outbox: InMemoryEmailSender,
) -> None:
    """El email es cliente de los dos talleres: aun así, el enlace de A no abre B."""
    email = new_email()
    await add_client(engines, two_workshops.a, email)
    await add_client(engines, two_workshops.b, email)
    _, token = await link_for(client, outbox, two_workshops.a, email)

    forged = await consume(client, two_workshops.b, token)
    assert forged.status_code == 400
    assert forged.json() == {"code": "portal_link_invalid"}
    assert "st-access-token" not in forged.headers
    # Con el taller de otro fijado, RLS no lo dejó ni ver: sigue sin usar.
    assert (await consume(client, two_workshops.a, token)).is_success


@pytest.mark.asyncio
async def test_t6_a_link_works_only_once(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    outbox: InMemoryEmailSender,
) -> None:
    email = new_email()
    await add_client(engines, two_workshops.a, email)
    workshop_id, token = await link_for(client, outbox, two_workshops.a, email)

    assert (await consume(client, workshop_id, token)).status_code == 204
    again = await consume(client, workshop_id, token)
    assert again.status_code == 400
    assert again.json() == {"code": "portal_link_invalid"}


@pytest.mark.asyncio
async def test_t6_two_uses_at_once_only_one_wins(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    """Dos transacciones reales: la segunda espera al bloqueo de la fila y, al
    seguir, ve el enlace ya usado."""
    client_id = await add_client(engines, two_workshops.a, new_email())
    token_hash = hash_token("enlace-de-prueba")
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO portal_links (workshop_id, client_id, token_hash,"
                " expires_at) VALUES (:w, :c, :h,"
                " clock_timestamp() + interval '15 minutes')"
            ),
            {"w": two_workshops.a, "c": client_id, "h": token_hash},
        )

    async with (
        open_transaction(two_workshops.a) as first,
        open_transaction(two_workshops.a) as second,
    ):
        assert await link_repo.use_if_open(first, token_hash) == client_id
        work = asyncio.create_task(link_repo.use_if_open(second, token_hash))
        await asyncio.sleep(GRACE)
        assert not work.done()  # esperando al bloqueo de la fila
        await first.commit()
        assert await finish(second, work) is None


@pytest.mark.asyncio
async def test_an_expired_link_opens_nothing(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    outbox: InMemoryEmailSender,
) -> None:
    email = new_email()
    await add_client(engines, two_workshops.a, email)
    workshop_id, token = await link_for(client, outbox, two_workshops.a, email)
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "UPDATE portal_links SET created_at = created_at - interval '1 hour',"
                " expires_at = expires_at - interval '1 hour'"
            )
        )
    assert (await consume(client, workshop_id, token)).status_code == 400


@pytest.mark.asyncio
async def test_a_used_link_cannot_be_reopened_even_by_the_owner(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    outbox: InMemoryEmailSender,
) -> None:
    email = new_email()
    await add_client(engines, two_workshops.a, email)
    workshop_id, token = await link_for(client, outbox, two_workshops.a, email)
    await consume(client, workshop_id, token)

    async with engines.owner.connect() as conn:
        # El dueño se salta la RLS forzada solo si la quita: aquí no hace falta,
        # porque el trigger salta antes de mirar nada más.
        await conn.execute(text("ALTER TABLE portal_links NO FORCE ROW LEVEL SECURITY"))
        with pytest.raises(DBAPIError, match="already closed"):
            await conn.execute(text("UPDATE portal_links SET used_at = NULL"))
        await conn.rollback()


# --- El cliente ya no es quien era -------------------------------------------


@pytest.mark.asyncio
async def test_changing_the_email_revokes_pending_links(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    outbox: InMemoryEmailSender,
) -> None:
    """El enlace se envió al email anterior: ya no es de este cliente (RF-47)."""
    email = new_email()
    client_id = await add_client(engines, two_workshops.a, email)
    workshop_id, token = await link_for(client, outbox, two_workshops.a, email)
    async with open_transaction(two_workshops.a) as session:
        await client_service.update_client(
            session, client_id, expected_version=1, changes={"email": new_email()}
        )
        await session.commit()
    assert (await consume(client, workshop_id, token)).status_code == 400


@pytest.mark.asyncio
async def test_anonymizing_revokes_pending_links(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    outbox: InMemoryEmailSender,
) -> None:
    email = new_email()
    client_id = await add_client(engines, two_workshops.a, email)
    workshop_id, token = await link_for(client, outbox, two_workshops.a, email)
    async with engines.platform.begin() as conn:
        user_id = await conn.scalar(
            text(
                "INSERT INTO users (supertokens_user_id, kind) VALUES (:s, 'staff')"
                " RETURNING id"
            ),
            {"s": f"st-{uuid4()}"},
        )
    async with open_transaction(two_workshops.a) as session:
        await client_service.anonymize_client(
            session, two_workshops.a, user_id, client_id, expected_version=1
        )
        await session.commit()
    async with engines.platform.begin() as conn:
        revoked = await conn.scalar(
            text("SELECT revoked_at IS NOT NULL FROM portal_links")
        )
    assert revoked
    assert (await consume(client, workshop_id, token)).status_code == 400


@pytest.mark.asyncio
async def test_an_archived_client_cannot_use_a_link_issued_before(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    outbox: InMemoryEmailSender,
) -> None:
    email = new_email()
    client_id = await add_client(engines, two_workshops.a, email)
    workshop_id, token = await link_for(client, outbox, two_workshops.a, email)
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE clients SET archived_at = clock_timestamp() WHERE id = :c"),
            {"c": client_id},
        )
    assert (await consume(client, workshop_id, token)).status_code == 400


@pytest.mark.asyncio
async def test_an_email_change_during_a_consume_waits_and_wins(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    outbox: InMemoryEmailSender,
) -> None:
    """Cambiar el email revoca los enlaces pendientes, con el bloqueo de su fila.
    Consumir pide el mismo bloqueo: espera, y luego ve el enlace revocado."""
    email = new_email()
    client_id = await add_client(engines, two_workshops.a, email)
    workshop_id, token = await link_for(client, outbox, two_workshops.a, email)

    async with open_transaction(two_workshops.a) as editing:
        await client_service.update_client(
            editing, client_id, expected_version=1, changes={"email": new_email()}
        )
        work = asyncio.create_task(portal_auth_service.consume(workshop_id, token))
        await asyncio.sleep(GRACE)
        assert not work.done()  # esperando a la fila del enlace
        await editing.commit()
    with pytest.raises(PortalLinkInvalidError):
        await asyncio.wait_for(work, timeout=10)


@pytest.mark.asyncio
async def test_an_email_change_while_a_link_is_issued_revokes_it_too(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    """Emitir bloquea al cliente: el cambio de email espera a que el enlace nuevo
    se confirme, y entonces lo ve y lo revoca. Sin el bloqueo, el cambio no lo
    vería (aún sin confirmar) y quedaría vivo para el email anterior."""
    email = new_email()
    client_id = await add_client(engines, two_workshops.a, email)

    async with (
        open_transaction(two_workshops.a) as issuing,
        open_transaction(two_workshops.a) as editing,
    ):
        assert await portal_auth_service._issue(
            issuing, two_workshops.a, email, "http://x"
        )
        work = asyncio.create_task(
            client_service.update_client(
                editing, client_id, expected_version=1, changes={"email": new_email()}
            )
        )
        await asyncio.sleep(GRACE)
        assert not work.done()  # esperando al bloqueo del cliente
        await issuing.commit()
        await finish(editing, work)
    async with engines.platform.begin() as conn:
        revoked = await conn.scalar(
            text("SELECT revoked_at IS NOT NULL FROM portal_links")
        )
    assert revoked


@pytest.mark.asyncio
async def test_the_session_stops_working_when_access_is_gone(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    outbox: InMemoryEmailSender,
) -> None:
    """La sesión se comprueba en cada petición (RNF-02): taller desactivado
    (RF-113) o cliente archivado ya no entran aunque la sesión siga viva."""
    email = new_email()
    client_id = await add_client(engines, two_workshops.a, email)
    session = await consume(
        client, *await link_for(client, outbox, two_workshops.a, email)
    )
    assert (await me(client, session)).status_code == 200

    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE workshops SET status = 'inactive' WHERE id = :w"),
            {"w": two_workshops.a},
        )
    refused = await me(client, session)
    assert refused.status_code == 403
    assert refused.json() == {"code": "portal_access_revoked"}

    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE workshops SET status = 'active' WHERE id = :w"),
            {"w": two_workshops.a},
        )
        await conn.execute(
            text("UPDATE clients SET archived_at = clock_timestamp() WHERE id = :c"),
            {"c": client_id},
        )
    assert (await me(client, session)).status_code == 403


# --- T10: siempre una sesión de cliente, del taller del enlace ----------------


@pytest.mark.asyncio
async def test_t10_an_email_that_is_also_staff_gets_a_client_session(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    outbox: InMemoryEmailSender,
    make_account: MakeAccount,
) -> None:
    """Ana es personal (con su cuenta de contraseña) y clienta del taller A."""
    staff = await make_account("staff")
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "UPDATE employees SET user_id ="
                " (SELECT id FROM users WHERE supertokens_user_id = :s)"
                " WHERE id = :e"
            ),
            {"s": staff.supertokens_user_id, "e": two_workshops.admin_b},
        )
    await add_client(engines, two_workshops.a, staff.email)

    session = await consume(
        client, *await link_for(client, outbox, two_workshops.a, staff.email)
    )
    assert session.status_code == 204
    token = claims(session)
    assert token["actor"] == "client"
    assert token["workshop_id"] == str(two_workshops.a)
    # Otro usuario de SuperTokens que el de su cuenta de personal (sin
    # vinculación de cuentas, arquitectura §2).
    assert token["sub"] != staff.supertokens_user_id
    # Con esta sesión no llega al taller B, donde es administradora.
    refused = await client.get(
        "/api/v1/workshop/me",
        headers={**bearer(session), "X-Workshop-Id": str(two_workshops.b)},
    )
    assert refused.status_code == 403
    assert refused.json() == {"code": "wrong_actor"}
    # Y su cuenta de personal sigue siendo de personal.
    staff_token = await sign_in(client, staff)
    staff_me = await client.get(
        "/api/v1/workshop/me", headers={"Authorization": f"Bearer {staff_token}"}
    )
    assert staff_me.json()["actor"] == "staff"


@pytest.mark.asyncio
async def test_t10_the_body_cannot_choose_the_client(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    outbox: InMemoryEmailSender,
) -> None:
    """Lo que la petición diga de más no entra en la sesión: el cliente sale del
    enlace guardado."""
    email = new_email()
    mine = await add_client(engines, two_workshops.a, email)
    other = await add_client(engines, two_workshops.a, new_email(), name="Otro")
    workshop_id, token = await link_for(client, outbox, two_workshops.a, email)
    session = await client.post(
        "/api/v1/portal/auth/consume",
        headers={"st-auth-mode": "header"},
        json={
            "workshop_id": str(workshop_id),
            "token": token,
            "client_id": str(other),
            "actor": "staff",
        },
    )
    assert claims(session)["client_id"] == str(mine)
    assert claims(session)["actor"] == "client"


# --- Las rutas de SuperTokens para passwordless no existen --------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/auth/signinup/code"),
        ("POST", "/api/auth/public/signinup/code"),
        ("POST", "/api/auth/signinup/code/resend"),
        ("POST", "/api/auth/signinup/code/consume"),
        ("GET", "/api/auth/passwordless/email/exists?email=a@example.com"),
        ("GET", "/api/auth/public/passwordless/email/exists?email=a@example.com"),
    ],
)
async def test_supertokens_passwordless_routes_are_closed(
    client: AsyncClient, method: str, path: str
) -> None:
    """Crearían códigos sin taller, y "¿existe este email?" diría quién es
    cliente (RF-41). Las nuestras son las únicas puertas (decisión 0006)."""
    response = await client.request(
        method,
        path,
        json={"email": "a@example.com"} if method == "POST" else None,
    )
    assert response.status_code == 404
