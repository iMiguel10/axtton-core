"""Clientes del taller (RF-10, RNF-01, RNF-03, RNF-15)."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.api.deps import get_email_sender
from app.infra.email import InMemoryEmailSender
from app.main import app
from app.scripts.reset_data import truncate_all
from tests.test_employees import AdminSession, add_mechanic, invite_and_accept
from tests.test_invitations import accept, bearer, new_workshop

URL = "/api/v1/workshop/clients"


async def open_workshop(client: AsyncClient, name: str) -> AdminSession:
    invited = await new_workshop(name)
    assert await accept(client, invited) == 204
    headers = {
        **await bearer(client, invited.email),
        "X-Workshop-Id": invited.workshop_id,
    }
    return AdminSession(invited, headers)


@pytest_asyncio.fixture
async def outbox() -> AsyncIterator[InMemoryEmailSender]:
    sender = InMemoryEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    yield sender
    app.dependency_overrides.pop(get_email_sender, None)


@pytest_asyncio.fixture
async def admin(client: AsyncClient) -> AdminSession:
    await truncate_all()
    return await open_workshop(client, "Talleres Pérez")


async def create(
    client: AsyncClient, headers: dict[str, str], **fields: Any
) -> dict[str, Any]:
    body = {"name": "María García", "phone": "600 111 222", **fields}
    response = await client.post(URL, json=body, headers=headers)
    assert response.status_code == 201, response.text
    created = await client.get(f"{URL}/{response.json()['id']}", headers=headers)
    result: dict[str, Any] = created.json()
    return result


@pytest_asyncio.fixture
async def mechanic(
    client: AsyncClient, admin: AdminSession, outbox: InMemoryEmailSender
) -> dict[str, str]:
    return await invite_and_accept(
        client, admin, outbox, await add_mechanic(client, admin)
    )


# --- Alta, lectura y listado -------------------------------------------------


@pytest.mark.asyncio
async def test_an_admin_creates_a_client_with_its_data_normalized(
    client: AsyncClient, admin: AdminSession
) -> None:
    created = await create(
        client,
        admin.headers,
        kind="company",
        name="  Transportes Ruiz SL  ",
        tax_id="b-12.345.678",
        email="Flota@Ruiz.Example.com",
        address="",
        language="en",
    )
    assert created["name"] == "Transportes Ruiz SL"
    assert created["tax_id"] == "B12345678"
    # El email es la llave del portal: siempre en minúsculas.
    assert created["email"] == "flota@ruiz.example.com"
    # Un opcional vacío es "no lo sé": nulo, no "".
    assert created["address"] is None
    assert (created["kind"], created["language"], created["version"]) == (
        "company",
        "en",
        1,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"phone": "600"},
        {"name": "   ", "phone": "600"},
        {"name": "Ana"},
        {"name": "Ana", "phone": "600", "email": "no-es-un-email"},
        {"name": "Ana", "phone": "600", "kind": "otro"},
        {"name": "Ana", "phone": "600", "language": "fr"},
    ],
)
async def test_invalid_data_is_a_422(
    client: AsyncClient, admin: AdminSession, body: dict[str, str]
) -> None:
    response = await client.post(URL, json=body, headers=admin.headers)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_the_list_is_by_name_and_filters_by_text(
    client: AsyncClient, admin: AdminSession
) -> None:
    for name, phone in (("Zoe", "611"), ("Álvaro", "622"), ("Bea", "633")):
        await create(client, admin.headers, name=name, phone=phone)

    listed = await client.get(URL, headers=admin.headers)
    # Con la intercalación de la base (en_US.utf8), "Á" va con la "A", no tras
    # la "Z" como iría comparando bytes.
    assert [c["name"] for c in listed.json()] == ["Álvaro", "Bea", "Zoe"]

    by_phone = await client.get(URL, params={"q": "62"}, headers=admin.headers)
    assert [c["name"] for c in by_phone.json()] == ["Álvaro"]
    by_name = await client.get(URL, params={"q": "zo"}, headers=admin.headers)
    assert [c["name"] for c in by_name.json()] == ["Zoe"]
    # Los comodines de LIKE se buscan como texto, no como comodines.
    wildcard = await client.get(URL, params={"q": "%"}, headers=admin.headers)
    assert wildcard.json() == []


@pytest.mark.asyncio
async def test_the_list_is_paginated(client: AsyncClient, admin: AdminSession) -> None:
    for n in range(3):
        await create(client, admin.headers, name=f"Cliente {n}")
    page = await client.get(
        URL, params={"limit": 2, "offset": 2}, headers=admin.headers
    )
    assert [c["name"] for c in page.json()] == ["Cliente 2"]
    too_big = await client.get(URL, params={"limit": 1000}, headers=admin.headers)
    assert too_big.status_code == 422


# --- Edición y bloqueo optimista (RNF-15) -----------------------------------


@pytest.mark.asyncio
async def test_editing_changes_only_what_is_sent_and_bumps_the_version(
    client: AsyncClient, admin: AdminSession
) -> None:
    maria = await create(client, admin.headers, notes="Prefiere WhatsApp")
    response = await client.patch(
        f"{URL}/{maria['id']}",
        json={"version": maria["version"], "phone": "699 000 000", "notes": None},
        headers=admin.headers,
    )
    assert response.status_code == 204
    after = (await client.get(f"{URL}/{maria['id']}", headers=admin.headers)).json()
    assert (after["phone"], after["notes"], after["name"]) == (
        "699 000 000",
        None,
        "María García",
    )
    assert after["version"] == maria["version"] + 1


@pytest.mark.asyncio
async def test_saving_over_someone_elses_change_is_a_409(
    client: AsyncClient, admin: AdminSession
) -> None:
    """Dos personas abren la ficha con la versión 1; la primera guarda y la
    segunda, que no ha visto su cambio, no lo pisa."""
    maria = await create(client, admin.headers)
    first = await client.patch(
        f"{URL}/{maria['id']}",
        json={"version": maria["version"], "phone": "611"},
        headers=admin.headers,
    )
    second = await client.patch(
        f"{URL}/{maria['id']}",
        json={"version": maria["version"], "phone": "622"},
        headers=admin.headers,
    )
    assert first.status_code == 204
    assert (second.status_code, second.json()) == (
        409,
        {"code": "modified_by_someone_else"},
    )
    after = (await client.get(f"{URL}/{maria['id']}", headers=admin.headers)).json()
    assert after["phone"] == "611"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["name", "phone", "kind", "language"])
async def test_a_required_field_cannot_be_nulled(
    client: AsyncClient, admin: AdminSession, field: str
) -> None:
    maria = await create(client, admin.headers)
    response = await client.patch(
        f"{URL}/{maria['id']}",
        json={"version": maria["version"], field: None},
        headers=admin.headers,
    )
    assert response.status_code == 422


# --- Email único por taller --------------------------------------------------


@pytest.mark.asyncio
async def test_two_clients_of_a_workshop_cannot_share_an_email(
    client: AsyncClient, admin: AdminSession
) -> None:
    """El email da acceso al portal (F4): dos clientes con el mismo email harían
    ambiguo de quién es el enlace mágico."""
    await create(client, admin.headers, email="maria@example.com")
    again = await client.post(
        URL,
        json={"name": "Otra", "phone": "6", "email": "MARIA@example.com"},
        headers=admin.headers,
    )
    assert (again.status_code, again.json()) == (409, {"code": "client_email_taken"})

    other = await create(client, admin.headers, name="Otra", email="otra@example.com")
    moved = await client.patch(
        f"{URL}/{other['id']}",
        json={"version": other["version"], "email": "maria@example.com"},
        headers=admin.headers,
    )
    assert (moved.status_code, moved.json()) == (409, {"code": "client_email_taken"})
    # Dos altas A LA VEZ con el mismo email: test_concurrency.py, con dos
    # transacciones reales intercaladas (con asyncio.gather sobre la API no
    # llegan a cruzarse y la prueba pasaría sin la guarda).


@pytest.mark.asyncio
async def test_clients_without_email_do_not_clash(
    client: AsyncClient, admin: AdminSession
) -> None:
    await create(client, admin.headers, name="Sin email 1")
    await create(client, admin.headers, name="Sin email 2", email=None)


# --- Archivar ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_archiving_hides_the_client_without_deleting_it(
    client: AsyncClient, admin: AdminSession
) -> None:
    maria = await create(client, admin.headers)
    archived = await client.post(
        f"{URL}/{maria['id']}/archive",
        json={"version": maria["version"]},
        headers=admin.headers,
    )
    assert archived.status_code == 204
    assert (await client.get(URL, headers=admin.headers)).json() == []
    in_archive = await client.get(URL, params={"archived": True}, headers=admin.headers)
    [row] = in_archive.json()
    assert row["archived_at"] is not None

    restored = await client.post(
        f"{URL}/{maria['id']}/unarchive",
        json={"version": row["version"]},
        headers=admin.headers,
    )
    assert restored.status_code == 204
    [back] = (await client.get(URL, headers=admin.headers)).json()
    assert back["archived_at"] is None


@pytest.mark.asyncio
async def test_archiving_with_an_old_version_is_a_409(
    client: AsyncClient, admin: AdminSession
) -> None:
    maria = await create(client, admin.headers)
    await client.patch(
        f"{URL}/{maria['id']}",
        json={"version": maria["version"], "phone": "6"},
        headers=admin.headers,
    )
    response = await client.post(
        f"{URL}/{maria['id']}/archive",
        json={"version": maria["version"]},
        headers=admin.headers,
    )
    assert response.status_code == 409


# --- Permisos (especificación §3, RNF-03) -----------------------------------


@pytest.mark.asyncio
async def test_a_mechanic_sees_clients_but_cannot_change_them(
    client: AsyncClient, admin: AdminSession, mechanic: dict[str, str]
) -> None:
    maria = await create(client, admin.headers)

    assert (await client.get(URL, headers=mechanic)).status_code == 200
    assert (
        await client.get(f"{URL}/{maria['id']}", headers=mechanic)
    ).status_code == 200

    attempts = [
        client.post(URL, json={"name": "X", "phone": "6"}, headers=mechanic),
        client.patch(
            f"{URL}/{maria['id']}",
            json={"version": maria["version"], "name": "X"},
            headers=mechanic,
        ),
        client.post(
            f"{URL}/{maria['id']}/archive",
            json={"version": maria["version"]},
            headers=mechanic,
        ),
        client.post(
            f"{URL}/{maria['id']}/unarchive",
            json={"version": maria["version"]},
            headers=mechanic,
        ),
    ]
    for attempt in attempts:
        response = await attempt
        assert (response.status_code, response.json()) == (
            403,
            {"code": "not_allowed"},
        )
    after = (await client.get(f"{URL}/{maria['id']}", headers=admin.headers)).json()
    assert after["version"] == maria["version"]


# --- Aislamiento entre talleres (RNF-01, RNF-07) ----------------------------


@pytest.mark.asyncio
async def test_a_client_of_another_workshop_is_a_404_for_everything(
    client: AsyncClient, admin: AdminSession
) -> None:
    """Desde el taller B, el cliente de A no existe: ni se lee, ni se edita, ni
    se archiva, ni aparece en el listado. 404, nunca 403 (no revela que existe)."""
    maria = await create(client, admin.headers, email="maria@example.com")

    b = (await open_workshop(client, "Taller B")).headers

    version = {"version": maria["version"]}
    responses = [
        await client.get(f"{URL}/{maria['id']}", headers=b),
        await client.patch(
            f"{URL}/{maria['id']}", json={**version, "name": "X"}, headers=b
        ),
        await client.post(f"{URL}/{maria['id']}/archive", json=version, headers=b),
    ]
    for response in responses:
        assert (response.status_code, response.json()) == (
            404,
            {"code": "client_not_found"},
        )
    assert (await client.get(URL, headers=b)).json() == []
    # El email es único por taller, no en toda la plataforma: la misma persona
    # en dos talleres son dos clientes (especificación §4).
    await create(client, b, email="maria@example.com")
    unchanged = (await client.get(f"{URL}/{maria['id']}", headers=admin.headers)).json()
    assert unchanged == maria
