"""Configuración del taller por su administrador (RF-02, F3 paso 1): datos
legales y ajustes, logotipo (decisión 0005) y tarifas de mano de obra."""

import asyncio
from io import BytesIO
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import text

from app.domain.settings import LOGO_MAX_UPLOAD_BYTES
from app.scripts.reset_data import truncate_all
from tests.conftest import Engines, TwoWorkshops
from tests.test_clients import open_workshop

# La prueba de la carrera usa los engines globales sin pasar por el fixture
# `client`, que es quien los cierra. Sin este fixture (autouse en su módulo, aquí
# importado), sus conexiones quedaban ligadas a su event loop y la prueba
# siguiente que los usara fallaba con "attached to a different loop" (CLAUDE.md
# §8); en la CI, test_superadmins.
from tests.test_concurrency import (
    GRACE,
    MakeAccount,
    dispose_global_engines,  # noqa: F401
    employee_with_access,
    finish,
    open_transaction,
)
from tests.test_employees import AdminSession

SETTINGS = "/api/v1/workshop/settings"
LOGO = f"{SETTINGS}/logo"
RATES = "/api/v1/workshop/labor-rates"


@pytest_asyncio.fixture
async def admin(client: AsyncClient) -> AdminSession:
    await truncate_all()
    return await open_workshop(client, "Talleres Pérez")


async def settings_of(client: AsyncClient, admin: AdminSession) -> dict[str, Any]:
    response = await client.get(SETTINGS, headers=admin.headers)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


async def audit_actions(
    client: AsyncClient, admin: AdminSession
) -> list[dict[str, Any]]:
    response = await client.get("/api/v1/workshop/audit", headers=admin.headers)
    assert response.status_code == 200, response.text
    entries: list[dict[str, Any]] = response.json()["entries"]
    return entries


def image(fmt: str, size: tuple[int, int] = (1600, 400)) -> bytes:
    out = BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, format=fmt)
    return out.getvalue()


# --- Datos del taller ---------------------------------------------------------


@pytest.mark.asyncio
async def test_the_admin_edits_the_legal_data_and_it_is_audited(
    client: AsyncClient, admin: AdminSession
) -> None:
    before = await settings_of(client, admin)
    assert before["has_logo"] is False
    response = await client.patch(
        SETTINGS,
        json={
            "version": before["version"],
            "name": "  Talleres Pérez Norte  ",
            "legal_name": "Talleres Pérez SL",
            "tax_id": "b-12.345.678",
            "reply_to_email": "Taller@Perez.Example.com",
            "industrial_registry_number": "28-12345",
            "address": "",
            "quote_validity_business_days": 15,
        },
        headers=admin.headers,
    )
    assert response.status_code == 204, response.text
    after = await settings_of(client, admin)
    assert after["name"] == "Talleres Pérez Norte"
    assert after["tax_id"] == "B12345678"
    assert after["reply_to_email"] == "taller@perez.example.com"
    assert after["address"] is None
    assert after["quote_validity_business_days"] == 15
    assert after["version"] == before["version"] + 1
    entry = (await audit_actions(client, admin))[0]
    assert entry["action"] == "workshop_settings_updated"
    # Solo lo que cambió, con el antes y el después. La dirección ya era nula.
    assert entry["details"]["name"] == ["Talleres Pérez", "Talleres Pérez Norte"]
    assert entry["details"]["quote_validity_business_days"] == [12, 15]
    assert "address" not in entry["details"]


@pytest.mark.asyncio
async def test_saving_without_changes_writes_nothing(
    client: AsyncClient, admin: AdminSession
) -> None:
    before = await settings_of(client, admin)
    response = await client.patch(
        SETTINGS,
        json={"version": before["version"], "name": before["name"]},
        headers=admin.headers,
    )
    assert response.status_code == 204
    assert (await settings_of(client, admin))["version"] == before["version"]
    actions = [e["action"] for e in await audit_actions(client, admin)]
    assert "workshop_settings_updated" not in actions


@pytest.mark.asyncio
async def test_rnf15_a_stale_version_gets_a_409(
    client: AsyncClient, admin: AdminSession
) -> None:
    version = (await settings_of(client, admin))["version"]
    first = await client.patch(
        SETTINGS, json={"version": version, "phone": "910"}, headers=admin.headers
    )
    assert first.status_code == 204
    second = await client.patch(
        SETTINGS, json={"version": version, "phone": "911"}, headers=admin.headers
    )
    assert second.status_code == 409
    assert second.json()["code"] == "modified_by_someone_else"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        # RF-33: nunca menos de 12 días hábiles.
        {"quote_validity_business_days": 11},
        {"quote_validity_business_days": 1000},
        {"default_vat_bp": 10_001},
        {"default_vat_bp": -1},
        {"name": ""},
        {"name": None},
        {"mechanics_see_sale_prices": None},
        {"reply_to_email": "no-es-un-email"},
    ],
)
async def test_invalid_settings_are_a_422(
    client: AsyncClient, admin: AdminSession, change: dict[str, Any]
) -> None:
    version = (await settings_of(client, admin))["version"]
    response = await client.patch(
        SETTINGS, json={"version": version, **change}, headers=admin.headers
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_what_belongs_to_the_platform_is_not_editable(
    client: AsyncClient, admin: AdminSession, engines: Engines
) -> None:
    """El esquema no conoce el estado, los límites ni la zona horaria: se ignoran
    aunque lleguen. Y aunque un fallo los dejara pasar, la base de datos los
    rechaza (test_rls_tables.py, 0012settings)."""
    version = (await settings_of(client, admin))["version"]
    response = await client.patch(
        SETTINGS,
        json={
            "version": version,
            "status": "inactive",
            "max_clients": 1_000_000,
            "timezone": "UTC",
        },
        headers=admin.headers,
    )
    assert response.status_code == 204
    async with engines.platform.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status, max_clients, timezone FROM workshops WHERE id = :w"
                ),
                {"w": admin.invited.workshop_id},
            )
        ).one()
    assert tuple(row) == ("active", 1000, "Europe/Madrid")


# --- Logotipo (decisión 0005) --------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fmt", "media_type"), [("PNG", "image/png"), ("JPEG", "image/jpeg")]
)
async def test_the_logo_is_stored_redrawn_as_a_reduced_png(
    client: AsyncClient, admin: AdminSession, fmt: str, media_type: str
) -> None:
    # Algo pegado detrás de la imagen (un "políglota") no sobrevive.
    uploaded = image(fmt) + b"<script>alert(1)</script>"
    response = await client.put(
        LOGO,
        content=uploaded,
        headers={**admin.headers, "Content-Type": media_type},
    )
    assert response.status_code == 204, response.text
    stored = await client.get(LOGO, headers=admin.headers)
    assert stored.status_code == 200
    assert stored.headers["content-type"] == "image/png"
    assert b"<script>" not in stored.content
    with Image.open(BytesIO(stored.content)) as logo:
        assert logo.format == "PNG"
        # Reducido a la caja de 800 × 400, sin deformarlo.
        assert logo.size == (800, 200)
    assert (await settings_of(client, admin))["has_logo"] is True
    actions = [e["action"] for e in await audit_actions(client, admin)]
    assert actions[0] == "workshop_logo_updated"


@pytest.mark.asyncio
async def test_a_new_logo_replaces_the_old_one_and_can_be_removed(
    client: AsyncClient, admin: AdminSession
) -> None:
    for size in ((100, 100), (300, 50)):
        response = await client.put(
            LOGO,
            content=image("PNG", size),
            headers={**admin.headers, "Content-Type": "image/png"},
        )
        assert response.status_code == 204
    with Image.open(
        BytesIO((await client.get(LOGO, headers=admin.headers)).content)
    ) as logo:
        assert logo.size == (300, 50)
    assert (await client.delete(LOGO, headers=admin.headers)).status_code == 204
    missing = await client.get(LOGO, headers=admin.headers)
    assert missing.status_code == 404
    assert missing.json()["code"] == "logo_not_found"
    # Quitarlo dos veces no es un error.
    assert (await client.delete(LOGO, headers=admin.headers)).status_code == 204


def huge_png_header() -> bytes:
    """Un PNG de 20.000 × 20.000 píxeles de un solo color: comprimido ocupa muy
    poco, pero descomprimido serían 1,6 GB. Debe rechazarse sin leerlo."""
    out = BytesIO()
    Image.new("1", (20_000, 20_000)).save(out, format="PNG")
    return out.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "content_type", "code"),
    [
        (b"esto no es una imagen", "image/png", "invalid_logo"),
        (b"GIF89a....", "image/gif", "invalid_logo"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml", "invalid_logo"),
        # Un GIF que dice ser PNG: solo se abren los decodificadores de PNG y JPEG.
        (b"GIF89a\x01\x00\x01\x00\x00\x00\x00;", "image/png", "invalid_logo"),
        (b"\x89PNG" + b"0" * LOGO_MAX_UPLOAD_BYTES, "image/png", "logo_too_large"),
    ],
)
async def test_what_is_not_a_usable_image_is_refused(
    client: AsyncClient,
    admin: AdminSession,
    body: bytes,
    content_type: str,
    code: str,
) -> None:
    response = await client.put(
        LOGO, content=body, headers={**admin.headers, "Content-Type": content_type}
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == code
    assert (await settings_of(client, admin))["has_logo"] is False


@pytest.mark.asyncio
async def test_a_decompression_bomb_is_refused_before_decoding_it(
    client: AsyncClient, admin: AdminSession
) -> None:
    bomb = huge_png_header()
    assert len(bomb) < LOGO_MAX_UPLOAD_BYTES
    response = await client.put(
        LOGO, content=bomb, headers={**admin.headers, "Content-Type": "image/png"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_logo"


# --- Tarifas de mano de obra ------------------------------------------------------


async def add_rate(
    client: AsyncClient, admin: AdminSession, name: str, price: int, **extra: Any
) -> str:
    response = await client.post(
        RATES,
        json={"name": name, "hourly_price_cents": price, **extra},
        headers=admin.headers,
    )
    assert response.status_code == 201, response.text
    rate_id: str = response.json()["id"]
    return rate_id


async def rates(
    client: AsyncClient, admin: AdminSession, archived: bool = False
) -> dict[str, dict[str, Any]]:
    response = await client.get(
        RATES, params={"archived": archived}, headers=admin.headers
    )
    assert response.status_code == 200
    return {r["name"]: r for r in response.json()}


@pytest.mark.asyncio
async def test_the_first_rate_is_the_default_and_marking_another_moves_it(
    client: AsyncClient, admin: AdminSession
) -> None:
    await add_rate(client, admin, "Mecánica", 4500)
    assert (await rates(client, admin))["Mecánica"]["is_default"] is True
    await add_rate(client, admin, "Electricidad", 5000)
    assert (await rates(client, admin))["Electricidad"]["is_default"] is False
    await add_rate(client, admin, "Chapa", 4000, is_default=True)
    listed = await rates(client, admin)
    assert [n for n, r in listed.items() if r["is_default"]] == ["Chapa"]
    # Ordenadas por nombre.
    assert list(listed) == ["Chapa", "Electricidad", "Mecánica"]


@pytest.mark.asyncio
async def test_editing_a_rate_is_audited_and_the_default_cannot_be_unset(
    client: AsyncClient, admin: AdminSession
) -> None:
    rate_id = await add_rate(client, admin, "Mecánica", 4500)
    response = await client.patch(
        f"{RATES}/{rate_id}",
        json={"version": 1, "hourly_price_cents": 4800},
        headers=admin.headers,
    )
    assert response.status_code == 204
    entry = (await audit_actions(client, admin))[0]
    assert entry["action"] == "labor_rate_updated"
    assert entry["details"] == {
        "hourly_price_cents": [4500, 4800],
        "labor_rate": "Mecánica",
    }
    # Quitar la marca sin dar otra dejaría al taller sin tarifa por defecto.
    unset = await client.patch(
        f"{RATES}/{rate_id}",
        json={"version": 2, "is_default": False},
        headers=admin.headers,
    )
    assert unset.status_code == 409
    assert unset.json()["code"] == "labor_rate_default_required"
    stale = await client.patch(
        f"{RATES}/{rate_id}", json={"version": 1, "name": "Otra"}, headers=admin.headers
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "modified_by_someone_else"


@pytest.mark.asyncio
async def test_two_current_rates_cannot_share_a_name(
    client: AsyncClient, admin: AdminSession
) -> None:
    first = await add_rate(client, admin, "Mecánica", 4500)
    response = await client.post(
        RATES, json={"name": "MECÁNICA", "hourly_price_cents": 1}, headers=admin.headers
    )
    assert response.status_code == 409
    assert response.json()["code"] == "labor_rate_name_taken"
    # Archivada, su nombre queda libre; desarchivarla con el nombre ocupado, no.
    await add_rate(client, admin, "Chapa", 4000, is_default=True)
    # Perder la marca de por defecto no sube su versión: nadie la estaba editando.
    archived = await client.post(
        f"{RATES}/{first}/archive", json={"version": 1}, headers=admin.headers
    )
    assert archived.status_code == 204, archived.text
    await add_rate(client, admin, "Mecánica", 5000)
    back = await client.post(
        f"{RATES}/{first}/unarchive", json={"version": 2}, headers=admin.headers
    )
    assert back.status_code == 409
    assert back.json()["code"] == "labor_rate_name_taken"


@pytest.mark.asyncio
async def test_the_default_rate_is_archived_only_when_it_is_the_last_one(
    client: AsyncClient, admin: AdminSession
) -> None:
    default = await add_rate(client, admin, "Mecánica", 4500)
    other = await add_rate(client, admin, "Chapa", 4000)
    refused = await client.post(
        f"{RATES}/{default}/archive", json={"version": 1}, headers=admin.headers
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "labor_rate_default_required"
    assert (
        await client.post(
            f"{RATES}/{other}/archive", json={"version": 1}, headers=admin.headers
        )
    ).status_code == 204
    # Ya es la única: se puede archivar, y el taller se queda sin tarifas.
    assert (
        await client.post(
            f"{RATES}/{default}/archive", json={"version": 1}, headers=admin.headers
        )
    ).status_code == 204
    assert await rates(client, admin) == {}
    assert set(await rates(client, admin, archived=True)) == {"Mecánica", "Chapa"}
    # La primera que vuelve, vuelve como la de por defecto.
    assert (
        await client.post(
            f"{RATES}/{other}/unarchive", json={"version": 2}, headers=admin.headers
        )
    ).status_code == 204
    assert (await rates(client, admin))["Chapa"]["is_default"] is True


@pytest.mark.asyncio
async def test_a_rate_of_another_workshop_does_not_exist(
    client: AsyncClient, admin: AdminSession
) -> None:
    """RNF-01: desde otro taller, la tarifa responde 404, no 403."""
    rate_id = await add_rate(client, admin, "Mecánica", 4500)
    other = await open_workshop(client, "Talleres Gómez")
    response = await client.patch(
        f"{RATES}/{rate_id}", json={"version": 1, "name": "Mía"}, headers=other.headers
    )
    assert response.status_code == 404
    assert await rates(client, other) == {}
    assert (await client.get(LOGO, headers=other.headers)).status_code == 404


# --- Concurrencia -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_rates_marked_as_default_at_once_leave_one_default(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """Sin `lock_labor_rates`, cada transacción quita la marca de la anterior sin
    ver a la otra, y la segunda choca con el índice único (409). Con el bloqueo,
    la segunda espera y gana: queda una sola, la última. Comprobado que falla
    con `lock_labor_rates` como no-op."""
    from app.services import settings as settings_service

    a = two_workshops.a
    user = (await employee_with_access(engines, make_account, a, "admin")).user_id
    ids: dict[str, UUID] = {}
    async with engines.platform.begin() as conn:
        for name, default in (("Mecánica", True), ("Chapa", False), ("Pintura", False)):
            ids[name] = await conn.scalar(
                text(
                    "INSERT INTO labor_rates"
                    " (workshop_id, name, hourly_price_cents, is_default)"
                    " VALUES (:w, :n, 4000, :d) RETURNING id"
                ),
                {"w": a, "n": name, "d": default},
            )

    def mark(session: Any, name: str) -> Any:
        return settings_service.update_labor_rate(
            session,
            a,
            user,
            ids[name],
            expected_version=1,
            changes={"is_default": True},
        )

    async with open_transaction(a) as first, open_transaction(a) as second:
        await mark(first, "Chapa")
        work = asyncio.create_task(mark(second, "Pintura"))
        await asyncio.sleep(GRACE)
        assert not work.done(), "la segunda debería esperar al bloqueo"
        await first.commit()
        outcome = await finish(second, work)

    assert outcome is None, outcome
    async with engines.platform.connect() as conn:
        defaults = (
            await conn.scalars(
                text(
                    "SELECT name FROM labor_rates WHERE workshop_id = :w AND is_default"
                ),
                {"w": a},
            )
        ).all()
    assert defaults == ["Pintura"]
