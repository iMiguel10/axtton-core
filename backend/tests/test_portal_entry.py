"""Lo que el taller ve del portal (F4 paso 7, decisión 0007).

El nombre corto del taller en la dirección (`/portal/{nombre}`), que es lo único
del portal que cruza talleres; el logotipo en la entrada; el límite de peticiones
de las páginas sin sesión; y la IP y el navegador de una decisión del portal, que
solo ve el administrador.
"""

import asyncio
from collections.abc import AsyncIterator
from io import BytesIO
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import text

from app.core.errors import ConflictError
from app.domain.portal import RESERVED_SLUGS, normalize_slug, slug_problem
from app.infra.email import InMemoryEmailSender
from app.infra.rate_limit import (
    LimitsRateLimiter,
    current_rate_limiter,
    set_rate_limiter,
)
from app.scripts.reset_data import truncate_all
from tests.conftest import Engines, TwoWorkshops
from tests.test_clients import AdminSession, open_workshop
from tests.test_concurrency import (
    GRACE,
    MakeAccount,
    dispose_global_engines,  # noqa: F401
    employee_with_access,
    finish,
    open_transaction,
)
from tests.test_employees import add_mechanic, invite_and_accept
from tests.test_portal_decision import post_decision
from tests.test_portal_orders import Portal, portal
from tests.test_quote_decision import sent_order
from tests.test_quotes import quotes_of
from tests.test_settings import LOGO, SETTINGS, image
from tests.test_work_orders import outbox

__all__ = ["outbox", "portal"]

ENTRY = "/api/v1/portal/workshops"


async def set_slug(
    client: AsyncClient, headers: dict[str, str], slug: str | None
) -> Any:
    current = await client.get(SETTINGS, headers=headers)
    return await client.patch(
        SETTINGS,
        json={"version": current.json()["version"], "portal_slug": slug},
        headers=headers,
    )


async def by_slug(client: AsyncClient, slug: str) -> Any:
    return await client.get(f"{ENTRY}/by-slug/{slug}")


@pytest_asyncio.fixture
async def two(client: AsyncClient) -> tuple[AdminSession, AdminSession]:
    await truncate_all()
    return (
        await open_workshop(client, "Talleres Martínez"),
        await open_workshop(client, "Taller Otro"),
    )


# --- Las reglas del nombre ----------------------------------------------------------


@pytest.mark.parametrize(
    "slug",
    ["abc", "talleres-martinez", "taller-2", "a1-b2-c3", "x" * 40],
)
def test_a_valid_name(slug: str) -> None:
    assert slug_problem(slug) is None


@pytest.mark.parametrize(
    "slug",
    [
        "ab",  # corto
        "x" * 41,  # largo
        "-taller",
        "taller-",
        "talleres--martinez",
        "talleres martinez",
        "martínez",  # sin tildes
        "taller_2",
        "taller.es",
        "taller/es",
        "",
    ],
)
def test_an_invalid_name(slug: str) -> None:
    assert slug_problem(slug) == "portal_slug_invalid"


@pytest.mark.parametrize("slug", sorted(RESERVED_SLUGS))
def test_a_page_of_the_portal_is_not_a_name(slug: str) -> None:
    assert slug_problem(slug) == "portal_slug_reserved"


def test_capitals_and_spaces_around_do_not_count() -> None:
    assert normalize_slug("  Talleres-Martinez ") == "talleres-martinez"


# --- Elegirlo -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_admin_chooses_the_name_and_the_portal_finds_the_workshop(
    client: AsyncClient, two: tuple[AdminSession, AdminSession]
) -> None:
    martinez, _ = two
    response = await set_slug(client, martinez.headers, "  Talleres-Martinez ")
    assert response.status_code == 204, response.text
    settings = await client.get(SETTINGS, headers=martinez.headers)
    assert settings.json()["portal_slug"] == "talleres-martinez"

    found = await by_slug(client, "talleres-martinez")
    assert found.status_code == 200, found.text
    assert found.json() == {"workshop_id": martinez.invited.workshop_id}
    # Escrito con mayúsculas en la dirección, el mismo taller.
    assert (await by_slug(client, "Talleres-Martinez")).json() == found.json()

    audit = await client.get("/api/v1/workshop/audit", headers=martinez.headers)
    entry = audit.json()["entries"][0]
    assert entry["action"] == "workshop_settings_updated"
    assert entry["details"]["portal_slug"] == [None, "talleres-martinez"]


@pytest.mark.asyncio
async def test_a_name_is_unique_in_the_whole_installation(
    client: AsyncClient, two: tuple[AdminSession, AdminSession]
) -> None:
    martinez, other = two
    assert (
        await set_slug(client, martinez.headers, "talleres-martinez")
    ).status_code == 204
    taken = await set_slug(client, other.headers, "TALLERES-MARTINEZ")
    assert (taken.status_code, taken.json()["code"]) == (409, "portal_slug_taken")
    # Sigue siendo del primero.
    found = await by_slug(client, "talleres-martinez")
    assert found.json()["workshop_id"] == martinez.invited.workshop_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("slug", "code"),
    [
        ("ab", "portal_slug_invalid"),
        ("martínez", "portal_slug_invalid"),
        ("login", "portal_slug_reserved"),
        ("orders", "portal_slug_reserved"),
    ],
)
async def test_an_unusable_name_is_a_422_with_its_code(
    client: AsyncClient,
    two: tuple[AdminSession, AdminSession],
    slug: str,
    code: str,
) -> None:
    response = await set_slug(client, two[0].headers, slug)
    assert (response.status_code, response.json()["code"]) == (422, code)


@pytest.mark.asyncio
async def test_changing_or_removing_the_name_frees_the_old_address(
    client: AsyncClient, two: tuple[AdminSession, AdminSession]
) -> None:
    """La dirección con el id sigue valiendo siempre (decisión 0006)."""
    martinez, other = two
    workshop_id = martinez.invited.workshop_id
    await set_slug(client, martinez.headers, "martinez-viejo")
    await set_slug(client, martinez.headers, "talleres-martinez")
    assert (await by_slug(client, "martinez-viejo")).status_code == 404
    assert (await by_slug(client, "talleres-martinez")).status_code == 200
    # El nombre que soltó lo puede coger otro.
    assert (await set_slug(client, other.headers, "martinez-viejo")).status_code == 204

    assert (await set_slug(client, martinez.headers, "")).status_code == 204
    assert (await client.get(SETTINGS, headers=martinez.headers)).json()[
        "portal_slug"
    ] is None
    assert (await by_slug(client, "talleres-martinez")).status_code == 404
    assert (await client.get(f"{ENTRY}/{workshop_id}")).status_code == 200


@pytest.mark.asyncio
async def test_a_mechanic_cannot_choose_it(
    client: AsyncClient,
    two: tuple[AdminSession, AdminSession],
    outbox: InMemoryEmailSender,
) -> None:
    martinez, _ = two
    mechanic = await invite_and_accept(
        client, martinez, outbox, await add_mechanic(client, martinez)
    )
    version = (await client.get(SETTINGS, headers=martinez.headers)).json()["version"]
    response = await client.patch(
        SETTINGS,
        json={"version": version, "portal_slug": "taller-del-mecanico"},
        headers=mechanic,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_two_workshops_taking_the_same_name_at_once_leave_one(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """La comprobación no puede mirar otros talleres: la última palabra es el índice
    único, y el segundo recibe un 409, no un 500."""
    from app.services import settings as settings_service

    async def version_of(workshop_id: Any) -> int:
        async with engines.platform.connect() as conn:
            found = await conn.scalar(
                text("SELECT version FROM workshops WHERE id = :w"), {"w": workshop_id}
            )
        return int(found)

    def take(session: Any, workshop_id: Any, user_id: Any, version: int) -> Any:
        return settings_service.update_workshop(
            session,
            workshop_id,
            user_id,
            expected_version=version,
            changes={"portal_slug": "el-mismo"},
        )

    a, b = two_workshops.a, two_workshops.b
    admin_a = await employee_with_access(engines, make_account, a, "admin")
    admin_b = await employee_with_access(engines, make_account, b, "admin")
    version_a, version_b = await version_of(a), await version_of(b)
    async with open_transaction(a) as first, open_transaction(b) as second:
        await take(first, a, admin_a.user_id, version_a)
        work = asyncio.create_task(take(second, b, admin_b.user_id, version_b))
        await asyncio.sleep(GRACE)
        assert not work.done(), "el segundo debería esperar al índice"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, ConflictError), outcome
    assert outcome.code == "portal_slug_taken"
    async with engines.platform.connect() as conn:
        owners = (
            await conn.scalars(
                text("SELECT id FROM workshops WHERE portal_slug = 'el-mismo'")
            )
        ).all()
    assert owners == [a]


# --- Buscarlo, sin sesión -------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_inactive_workshop_is_not_found_by_its_name(
    client: AsyncClient, two: tuple[AdminSession, AdminSession], engines: Engines
) -> None:
    martinez, _ = two
    await set_slug(client, martinez.headers, "talleres-martinez")
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE workshops SET status = 'inactive' WHERE id = :w"),
            {"w": martinez.invited.workshop_id},
        )
    assert (await by_slug(client, "talleres-martinez")).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "slug", ["no-existe", "login", "ab", "con%20espacio", "x" * 300]
)
async def test_what_is_not_a_workshop_is_the_same_404(
    client: AsyncClient, two: tuple[AdminSession, AdminSession], slug: str
) -> None:
    response = await by_slug(client, slug)
    assert (response.status_code, response.json()) == (
        404,
        {"code": "workshop_not_found"},
    )


@pytest.mark.asyncio
async def test_the_lookup_gives_only_the_id(
    client: AsyncClient, two: tuple[AdminSession, AdminSession]
) -> None:
    """Ni el nombre, ni los datos legales, ni nada de los demás talleres: el nombre
    lo da la entrada después, ya con el taller fijado."""
    await set_slug(client, two[0].headers, "talleres-martinez")
    found = await by_slug(client, "talleres-martinez")
    assert set(found.json()) == {"workshop_id"}


@pytest.mark.asyncio
async def test_the_platform_lookup_only_answers_an_exact_active_name(
    client: AsyncClient, two: tuple[AdminSession, AdminSession]
) -> None:
    """La vía de plataforma, por sí sola: ni prefijos ni comodines."""
    from app.platform.portal_entry import workshop_id_by_slug

    await set_slug(client, two[0].headers, "talleres-martinez")
    assert str(await workshop_id_by_slug("talleres-martinez")) == (
        two[0].invited.workshop_id
    )
    for guess in (
        "talleres",
        "talleres-%",
        "%",
        "talleres-martine_",
        "TALLERES-MARTINEZ",
    ):
        assert await workshop_id_by_slug(guess) is None, guess


# --- El logotipo en la entrada --------------------------------------------------------


@pytest.mark.asyncio
async def test_the_entry_shows_the_logo_redrawn_by_the_server(
    client: AsyncClient, two: tuple[AdminSession, AdminSession]
) -> None:
    martinez, other = two
    uploaded = image("JPEG") + b"<script>alert(1)</script>"
    response = await client.put(
        LOGO,
        content=uploaded,
        headers={**martinez.headers, "Content-Type": "image/jpeg"},
    )
    assert response.status_code == 204, response.text
    workshop_id = martinez.invited.workshop_id

    entry = await client.get(f"{ENTRY}/{workshop_id}")
    assert entry.json() == {"workshop_name": "Talleres Martínez", "has_logo": True}
    logo = await client.get(f"{ENTRY}/{workshop_id}/logo")
    assert logo.status_code == 200
    assert logo.headers["content-type"] == "image/png"
    assert logo.headers["x-content-type-options"] == "nosniff"
    assert logo.headers["content-security-policy"] == "default-src 'none'"
    assert logo.content == (await client.get(LOGO, headers=martinez.headers)).content
    assert b"<script>" not in logo.content
    with Image.open(BytesIO(logo.content)) as drawn:
        assert drawn.format == "PNG"

    # El otro taller no tiene: 404, no el del primero.
    other_id = other.invited.workshop_id
    assert (await client.get(f"{ENTRY}/{other_id}")).json()["has_logo"] is False
    missing = await client.get(f"{ENTRY}/{other_id}/logo")
    assert (missing.status_code, missing.json()["code"]) == (404, "logo_not_found")


@pytest.mark.asyncio
async def test_an_inactive_or_unknown_workshop_has_no_logo(
    client: AsyncClient, two: tuple[AdminSession, AdminSession], engines: Engines
) -> None:
    martinez, _ = two
    await client.put(
        LOGO,
        content=image("PNG"),
        headers={**martinez.headers, "Content-Type": "image/png"},
    )
    workshop_id = martinez.invited.workshop_id
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE workshops SET status = 'inactive' WHERE id = :w"),
            {"w": workshop_id},
        )
    for target in (workshop_id, str(uuid4())):
        response = await client.get(f"{ENTRY}/{target}/logo")
        assert (response.status_code, response.json()["code"]) == (
            404,
            "workshop_not_found",
        )


# --- El límite de las páginas sin sesión ----------------------------------------------


@pytest_asyncio.fixture
async def limiter() -> AsyncIterator[None]:
    previous = current_rate_limiter()
    set_rate_limiter(LimitsRateLimiter("async+memory://"))
    yield
    set_rate_limiter(previous)


@pytest.mark.asyncio
async def test_guessing_names_is_limited_per_ip(
    client: AsyncClient, two: tuple[AdminSession, AdminSession], limiter: Any
) -> None:
    """Las tres páginas cuentan juntas: probar nombres no se esquiva cambiando de
    ruta."""
    workshop_id = two[0].invited.workshop_id
    for i in range(20):
        assert (await by_slug(client, f"prueba-{i}")).status_code == 404
        assert (await client.get(f"{ENTRY}/{workshop_id}")).status_code == 200
        assert (await client.get(f"{ENTRY}/{workshop_id}/logo")).status_code == 404
    limited = await by_slug(client, "otra-mas")
    assert (limited.status_code, limited.json()["code"]) == (429, "rate_limited")
    assert (await client.get(f"{ENTRY}/{workshop_id}")).status_code == 429


# --- La IP y el navegador, solo para el administrador ----------------------------------


@pytest.mark.asyncio
async def test_only_the_admin_sees_the_ip_and_browser_of_a_portal_decision(
    client: AsyncClient, portal: Portal, outbox: InMemoryEmailSender
) -> None:
    order_id, quote_id = await sent_order(client, portal.shop)
    assert (await post_decision(client, portal.maria, quote_id)).status_code == 204

    (seen_by_admin,) = await quotes_of(client, portal.shop.headers, order_id)
    decision = seen_by_admin["decision"]
    assert decision["ip"] == "127.0.0.1"
    assert decision["user_agent"].startswith("Mozilla/5.0")

    mechanic = await invite_and_accept(
        client, portal.shop.admin, outbox, await add_mechanic(client, portal.shop.admin)
    )
    (seen_by_mechanic,) = await quotes_of(client, mechanic, order_id)
    assert seen_by_mechanic["decision"]["ip"] is None
    assert seen_by_mechanic["decision"]["user_agent"] is None
    # Lo demás de la decisión, sí.
    assert seen_by_mechanic["decision"]["channel"] == "portal"
