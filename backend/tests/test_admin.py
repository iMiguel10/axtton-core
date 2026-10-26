"""Superadministrador: alta, listado, desactivación y límites de talleres (RF-110 a RF-114)."""

import ast
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.api.deps import get_email_sender
from app.core.config import get_settings
from app.infra.email import DisabledEmailSender, InMemoryEmailSender
from app.main import app
from app.scripts.reset_data import truncate_all
from tests.conftest import Account, Engines, sign_in

MakeAccount = Callable[[str], Awaitable[Account]]
NEW_WORKSHOP = {
    "name": "Talleres Pérez",
    "admin_name": "Ana López",
    "admin_email": "ana@talleresperez.es",
}


@pytest_asyncio.fixture
async def outbox() -> AsyncIterator[InMemoryEmailSender]:
    """Sustituye el correo real por uno en memoria durante la prueba."""
    sender = InMemoryEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    yield sender
    app.dependency_overrides.pop(get_email_sender, None)


@pytest_asyncio.fixture
async def superadmin(client: AsyncClient, make_account: MakeAccount) -> dict[str, str]:
    await truncate_all()
    token = await sign_in(client, await make_account("superadmin"))
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_creating_a_workshop_invites_its_first_admin(
    client: AsyncClient,
    engines: Engines,
    superadmin: dict[str, str],
    outbox: InMemoryEmailSender,
) -> None:
    response = await client.post(
        "/api/v1/admin/workshops", json=NEW_WORKSHOP, headers=superadmin
    )
    assert response.status_code == 201
    workshop_id = response.json()["workshop_id"]
    assert response.json()["invitation_email_sent"] is True

    [email] = outbox.sent
    assert email.to == "ana@talleresperez.es"
    link = f"/invitations/{workshop_id}/"
    assert link in email.body
    token = email.body.split(link, 1)[1].split()[0]

    async with engines.platform.connect() as conn:
        role, has_user = (
            await conn.execute(
                text(
                    "SELECT role, user_id IS NOT NULL FROM employees WHERE workshop_id = :w"
                ),
                {"w": workshop_id},
            )
        ).one()
        stored_hash = await conn.scalar(
            text("SELECT token_hash FROM invitations WHERE workshop_id = :w"),
            {"w": workshop_id},
        )
        audit = (
            await conn.execute(
                text(
                    "SELECT workshop_id, details FROM audit_log"
                    " WHERE action = 'workshop_created'"
                )
            )
        ).one()
    # El primer administrador existe como ficha, aún sin cuenta: la crea al aceptar.
    assert (role, has_user) == ("admin", False)
    # De la invitación solo se guarda el hash, nunca el token del enlace.
    assert token.encode() not in bytes(stored_hash)
    # Acción de plataforma: sin taller (ningún taller la ve) y sin datos personales.
    assert audit.workshop_id is None
    assert audit.details == {"name": "Talleres Pérez"}


@pytest.mark.asyncio
async def test_without_smtp_the_workshop_is_created_and_says_no_email_went_out(
    client: AsyncClient, engines: Engines, superadmin: dict[str, str]
) -> None:
    app.dependency_overrides[get_email_sender] = DisabledEmailSender
    try:
        response = await client.post(
            "/api/v1/admin/workshops", json=NEW_WORKSHOP, headers=superadmin
        )
    finally:
        app.dependency_overrides.pop(get_email_sender, None)
    assert response.json()["invitation_email_sent"] is False
    async with engines.platform.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM invitations")) == 1


@pytest.mark.asyncio
async def test_listing_shows_account_data_and_counts_only(
    client: AsyncClient, superadmin: dict[str, str], outbox: InMemoryEmailSender
) -> None:
    await client.post("/api/v1/admin/workshops", json=NEW_WORKSHOP, headers=superadmin)
    [workshop] = (
        await client.get("/api/v1/admin/workshops", headers=superadmin)
    ).json()
    # RNF-08: nada operativo. De los administradores, solo el nombre (RF-114),
    # nunca su email ni el resto de empleados.
    assert set(workshop) == {
        "id",
        "name",
        "status",
        "created_at",
        "max_employees_with_access",
        "employees_with_access",
        "pending_invitations",
        "admins",
    }
    assert workshop["employees_with_access"] == 0
    assert workshop["pending_invitations"] == 1
    # El primer administrador sale aunque aún no haya aceptado la invitación.
    assert workshop["admins"] == [NEW_WORKSHOP["admin_name"]]
    assert NEW_WORKSHOP["admin_email"] not in str(workshop)


@pytest.mark.asyncio
async def test_listing_names_only_the_active_admins_of_each_workshop(
    client: AsyncClient,
    superadmin: dict[str, str],
    outbox: InMemoryEmailSender,
    engines: Engines,
) -> None:
    """Ni mecánicos ni administradores desactivados, y cada uno en su taller."""
    await client.post("/api/v1/admin/workshops", json=NEW_WORKSHOP, headers=superadmin)
    other = {**NEW_WORKSHOP, "name": "Taller B", "admin_name": "Berta"}
    await client.post("/api/v1/admin/workshops", json=other, headers=superadmin)
    listed = (await client.get("/api/v1/admin/workshops", headers=superadmin)).json()
    first = next(w for w in listed if w["name"] == NEW_WORKSHOP["name"])
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO employees (workshop_id, name, role) VALUES"
                " (:w, 'Mecánico', 'mechanic'),"
                " (:w, 'Antigua', 'admin')"
            ),
            {"w": first["id"]},
        )
        await conn.execute(
            text("UPDATE employees SET active = false WHERE name = 'Antigua'")
        )

    listed = (await client.get("/api/v1/admin/workshops", headers=superadmin)).json()
    admins = {w["name"]: w["admins"] for w in listed}
    assert admins == {
        NEW_WORKSHOP["name"]: [NEW_WORKSHOP["admin_name"]],
        "Taller B": ["Berta"],
    }


@pytest.mark.asyncio
async def test_single_workshop_installation_refuses_a_second_workshop(
    client: AsyncClient,
    superadmin: dict[str, str],
    outbox: InMemoryEmailSender,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "installation_mode", "single")
    first = await client.post(
        "/api/v1/admin/workshops", json=NEW_WORKSHOP, headers=superadmin
    )
    second = await client.post(
        "/api/v1/admin/workshops",
        json={**NEW_WORKSHOP, "name": "Otro taller"},
        headers=superadmin,
    )
    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json() == {"code": "single_workshop_installation"}


@pytest.mark.asyncio
async def test_deactivating_and_changing_limits_is_audited(
    client: AsyncClient,
    engines: Engines,
    superadmin: dict[str, str],
    outbox: InMemoryEmailSender,
) -> None:
    created = await client.post(
        "/api/v1/admin/workshops", json=NEW_WORKSHOP, headers=superadmin
    )
    workshop_id = created.json()["workshop_id"]
    response = await client.patch(
        f"/api/v1/admin/workshops/{workshop_id}",
        json={"status": "inactive", "max_employees_with_access": 5},
        headers=superadmin,
    )
    assert response.status_code == 204
    [workshop] = (
        await client.get("/api/v1/admin/workshops", headers=superadmin)
    ).json()
    assert (workshop["status"], workshop["max_employees_with_access"]) == (
        "inactive",
        5,
    )
    async with engines.platform.connect() as conn:
        details = await conn.scalar(
            text("SELECT details FROM audit_log WHERE action = 'workshop_updated'")
        )
    assert details == {
        "status": ["active", "inactive"],
        "max_employees_with_access": [20, 5],
    }


@pytest.mark.asyncio
async def test_updating_an_unknown_workshop_is_404(
    client: AsyncClient, superadmin: dict[str, str]
) -> None:
    response = await client.patch(
        "/api/v1/admin/workshops/00000000-0000-0000-0000-000000000000",
        json={"status": "inactive"},
        headers=superadmin,
    )
    assert response.status_code == 404


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


# Las únicas excepciones a R8, con nombre (arquitectura §4, "Las vías que cruzan
# talleres"): (fichero relativo a app/api/v1, módulo de plataforma que importa).
# Añadir una aquí es una decisión de diseño, no un arreglo para que pase la prueba.
R8_EXCEPTIONS = {
    # Selector de taller: saber en qué talleres trabaja la persona (RF-08).
    ("workshop/router.py", "app.platform.memberships"),
}


def test_r8_workshop_and_portal_never_import_the_platform_module() -> None:
    """Solo /admin (y los comandos de servidor) pueden usar el rol que se salta RLS.

    Se leen los imports con el analizador de Python, no con una búsqueda de
    texto: un comentario que mencione app.platform no cuenta, y un import
    partido en varias líneas sí. Las excepciones están en R8_EXCEPTIONS, cada
    una con su fichero y su módulo exactos.
    """
    api_dir = Path(__file__).resolve().parent.parent / "app" / "api" / "v1"
    checked = 0
    for prefix in ("workshop", "portal"):
        for path in (api_dir / prefix).rglob("*.py"):
            checked += 1
            relative = path.relative_to(api_dir).as_posix()
            offending = {
                module
                for module in _imports(path)
                if module.startswith("app.platform")
                and (relative, module) not in R8_EXCEPTIONS
            }
            assert offending == set(), f"{relative} importa {offending}"
    # Prueba de control: si no encontrara ficheros, no probaría nada.
    assert checked >= 2
