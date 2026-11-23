"""El catálogo de piezas (F7 paso 1, RF-90, especificación §3, RNF-16)."""

from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.domain.limits import Resource
from app.infra.email import InMemoryEmailSender
from app.scripts.reset_data import truncate_all
from tests.test_clients import open_workshop, outbox  # noqa: F401
from tests.test_employees import AdminSession, add_mechanic, invite_and_accept
from tests.test_limits import refused, set_limit
from tests.test_settings import audit_actions

URL = "/api/v1/workshop/parts"


@pytest_asyncio.fixture
async def admin(client: AsyncClient) -> AdminSession:
    await truncate_all()
    return await open_workshop(client, "Talleres Pérez")


@pytest_asyncio.fixture
async def mechanic(
    client: AsyncClient,
    admin: AdminSession,
    outbox: InMemoryEmailSender,  # noqa: F811
) -> dict[str, str]:
    return await invite_and_accept(
        client, admin, outbox, await add_mechanic(client, admin)
    )


BATTERY = {
    "reference": "BAT-70",
    "description": "Batería 70 Ah",
    "brand": "Varta",
    "cost_price_cents": 6000,
    "sale_price_cents": 9500,
    "vat_bp": 2100,
    "warranty_months": 24,
    "min_stock": "2",
}


async def create(
    client: AsyncClient, headers: dict[str, str], **fields: Any
) -> dict[str, Any]:
    response = await client.post(URL, json={**BATTERY, **fields}, headers=headers)
    assert response.status_code == 201, response.text
    created = await client.get(f"{URL}/{response.json()['id']}", headers=headers)
    assert created.status_code == 200, created.text
    result: dict[str, Any] = created.json()
    return result


async def listed(
    client: AsyncClient, headers: dict[str, str], **params: Any
) -> dict[str, Any]:
    response = await client.get(URL, params=params, headers=headers)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


# --- Alta, lectura y listado -------------------------------------------------


@pytest.mark.asyncio
async def test_an_admin_adds_a_part_to_the_catalog(
    client: AsyncClient, admin: AdminSession
) -> None:
    part = await create(client, admin.headers, brand="  ")
    assert part["reference"] == "BAT-70"
    assert (part["cost_price_cents"], part["sale_price_cents"]) == (6000, 9500)
    # Una marca vacía es "no la sé": nula, no "".
    assert part["brand"] is None
    assert part["part_condition"] == "new"
    assert (part["tracks_stock"], part["min_stock"], part["warranty_months"]) == (
        True,
        "2.000",
        24,
    )
    assert part["archived_at"] is None
    assert part["version"] == 1


@pytest.mark.asyncio
async def test_without_vat_a_part_takes_the_workshop_default(
    client: AsyncClient, admin: AdminSession
) -> None:
    body = {k: v for k, v in BATTERY.items() if k != "vat_bp"}
    response = await client.post(URL, json=body, headers=admin.headers)
    assert response.status_code == 201, response.text
    part = (
        await client.get(f"{URL}/{response.json()['id']}", headers=admin.headers)
    ).json()
    assert part["vat_bp"] == 2100


@pytest.mark.asyncio
async def test_the_reference_is_unique_regardless_of_case_even_archived(
    client: AsyncClient, admin: AdminSession
) -> None:
    part = await create(client, admin.headers)
    response = await client.post(
        URL, json={**BATTERY, "reference": "bat-70"}, headers=admin.headers
    )
    refused(response, "part_reference_taken")
    # Archivada sigue nombrando a su pieza en su historial: no se reutiliza.
    archived = await client.post(
        f"{URL}/{part['id']}/archive", json={"version": 1}, headers=admin.headers
    )
    assert archived.status_code == 204
    response = await client.post(URL, json=BATTERY, headers=admin.headers)
    refused(response, "part_reference_taken")


@pytest.mark.asyncio
async def test_the_list_searches_reference_brand_and_description_without_accents(
    client: AsyncClient, admin: AdminSession
) -> None:
    await create(client, admin.headers)
    await create(
        client,
        admin.headers,
        reference="PAS-01",
        description="Pastillas de freno delanteras",
        brand="Bosch",
        warranty_months=None,
    )
    for term, expected in (
        ("bateria", ["BAT-70"]),
        ("BOSCH", ["PAS-01"]),
        ("pas-0", ["PAS-01"]),
        ("ah", ["BAT-70"]),
        ("%", []),
        (None, ["BAT-70", "PAS-01"]),
    ):
        page = await listed(client, admin.headers, **({"q": term} if term else {}))
        assert [p["reference"] for p in page["parts"]] == expected, term


@pytest.mark.asyncio
async def test_an_archived_part_leaves_the_list_and_comes_back(
    client: AsyncClient, admin: AdminSession
) -> None:
    part = await create(client, admin.headers)
    path = f"{URL}/{part['id']}"
    assert (
        await client.post(f"{path}/archive", json={"version": 1}, headers=admin.headers)
    ).status_code == 204
    assert (await listed(client, admin.headers))["parts"] == []
    archived = await listed(client, admin.headers, archived="true")
    assert [p["id"] for p in archived["parts"]] == [part["id"]]
    # Archivada no se edita: antes se desarchiva.
    stale = await client.patch(
        path, json={"version": 2, "sale_price_cents": 1}, headers=admin.headers
    )
    refused(stale, "part_archived")
    assert (
        await client.post(
            f"{path}/unarchive", json={"version": 2}, headers=admin.headers
        )
    ).status_code == 204
    assert [p["id"] for p in (await listed(client, admin.headers))["parts"]] == [
        part["id"]
    ]


# --- Edición ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_editing_with_an_old_version_is_a_409(
    client: AsyncClient, admin: AdminSession
) -> None:
    part = await create(client, admin.headers)
    path = f"{URL}/{part['id']}"
    first = await client.patch(
        path, json={"version": 1, "description": "Batería 74 Ah"}, headers=admin.headers
    )
    assert first.status_code == 204, first.text
    second = await client.patch(
        path, json={"version": 1, "description": "Otra"}, headers=admin.headers
    )
    refused(second, "modified_by_someone_else")
    assert (await client.get(path, headers=admin.headers)).json()[
        "description"
    ] == "Batería 74 Ah"


@pytest.mark.asyncio
async def test_not_counting_the_stock_drops_the_minimum(
    client: AsyncClient, admin: AdminSession
) -> None:
    part = await create(client, admin.headers)
    path = f"{URL}/{part['id']}"
    response = await client.patch(
        path, json={"version": 1, "tracks_stock": False}, headers=admin.headers
    )
    assert response.status_code == 204, response.text
    updated = (await client.get(path, headers=admin.headers)).json()
    assert (updated["tracks_stock"], updated["min_stock"]) == (False, None)
    # Un mínimo sin contar el stock no significa nada (RF-95).
    response = await client.patch(
        path, json={"version": 2, "min_stock": "1"}, headers=admin.headers
    )
    refused(response, "part_min_stock_without_stock")
    response = await client.post(
        URL,
        json={**BATTERY, "reference": "X", "tracks_stock": False},
        headers=admin.headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields",
    [
        {"reference": ""},
        {"reference": "   "},
        {"description": ""},
        {"sale_price_cents": -1},
        {"cost_price_cents": -1},
        {"vat_bp": 10001},
        {"warranty_months": 3},
        {"warranty_months": 121},
        {"min_stock": "-1"},
        {"min_stock": "0.0001"},
        {"part_condition": "broken"},
        {"sale_price_cents": None},
    ],
)
async def test_invalid_parts_are_a_422(
    client: AsyncClient, admin: AdminSession, fields: dict[str, Any]
) -> None:
    response = await client.post(URL, json={**BATTERY, **fields}, headers=admin.headers)
    assert response.status_code == 422, (fields, response.text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field", ["reference", "description", "sale_price_cents", "vat_bp", "tracks_stock"]
)
async def test_a_required_field_cannot_be_nulled(
    client: AsyncClient, admin: AdminSession, field: str
) -> None:
    part = await create(client, admin.headers)
    response = await client.patch(
        f"{URL}/{part['id']}", json={"version": 1, field: None}, headers=admin.headers
    )
    assert response.status_code == 422, response.text


# --- Auditoría (RNF-16) ------------------------------------------------------


@pytest.mark.asyncio
async def test_the_creation_and_each_price_change_are_audited(
    client: AsyncClient, admin: AdminSession
) -> None:
    part = await create(client, admin.headers)
    path = f"{URL}/{part['id']}"
    # Cambiar solo la descripción no es un cambio de precio: no se audita.
    await client.patch(
        path, json={"version": 1, "description": "Batería 74 Ah"}, headers=admin.headers
    )
    await client.patch(
        path,
        json={"version": 2, "sale_price_cents": 9900, "vat_bp": 2100},
        headers=admin.headers,
    )
    changed, created = (await audit_actions(client, admin))[:2]
    assert created["action"] == "part_created"
    assert created["target_name"] == "BAT-70"
    assert created["details"] == {
        "part": "BAT-70",
        "cost_price_cents": 6000,
        "sale_price_cents": 9500,
        "vat_bp": 2100,
    }
    assert changed["action"] == "part_prices_changed"
    # Solo lo que cambió, con el valor anterior y el nuevo.
    assert changed["details"] == {"part": "BAT-70", "sale_price_cents": [9500, 9900]}


# --- Permisos (especificación §3) --------------------------------------------


@pytest.mark.asyncio
async def test_a_mechanic_sees_the_catalog_without_costs_and_cannot_change_it(
    client: AsyncClient, admin: AdminSession, mechanic: dict[str, str]
) -> None:
    part = await create(client, admin.headers)
    page = await listed(client, mechanic)
    (seen,) = page["parts"]
    assert seen["cost_price_cents"] is None
    assert seen["sale_price_cents"] == 9500
    assert page["prices_hidden"] is False
    one = await client.get(f"{URL}/{part['id']}", headers=mechanic)
    assert one.json()["cost_price_cents"] is None

    for method, path, body in (
        ("POST", URL, {**BATTERY, "reference": "Y"}),
        ("PATCH", f"{URL}/{part['id']}", {"version": 1, "description": "x"}),
        ("POST", f"{URL}/{part['id']}/archive", {"version": 1}),
        ("POST", f"{URL}/{part['id']}/unarchive", {"version": 1}),
    ):
        response = await client.request(method, path, json=body, headers=mechanic)
        assert response.status_code == 403, (method, path)
        assert response.json()["code"] == "not_allowed"


@pytest.mark.asyncio
async def test_a_mechanic_does_not_see_sale_prices_if_the_workshop_says_so(
    client: AsyncClient, admin: AdminSession, mechanic: dict[str, str]
) -> None:
    part = await create(client, admin.headers)
    settings = await client.get("/api/v1/workshop/settings", headers=admin.headers)
    await client.patch(
        "/api/v1/workshop/settings",
        json={
            "version": settings.json()["version"],
            "mechanics_see_sale_prices": False,
        },
        headers=admin.headers,
    )
    page = await listed(client, mechanic)
    assert page["prices_hidden"] is True
    assert page["parts"][0]["sale_price_cents"] is None
    one = await client.get(f"{URL}/{part['id']}", headers=mechanic)
    assert one.json()["sale_price_cents"] is None
    # El administrador lo ve todo.
    assert (await listed(client, admin.headers))["parts"][0]["sale_price_cents"] == 9500


@pytest.mark.asyncio
async def test_a_part_of_another_workshop_does_not_exist(
    client: AsyncClient, admin: AdminSession
) -> None:
    part = await create(client, admin.headers)
    other = await open_workshop(client, "Taller Ajeno")
    assert (await listed(client, other.headers))["parts"] == []
    for method, path, body in (
        ("GET", f"{URL}/{part['id']}", None),
        ("PATCH", f"{URL}/{part['id']}", {"version": 1, "description": "x"}),
        ("POST", f"{URL}/{part['id']}/archive", {"version": 1}),
    ):
        response = await client.request(method, path, json=body, headers=other.headers)
        assert response.status_code == 404, (method, path)
        assert response.json()["code"] == "part_not_found"
    # Y su referencia no choca con la del otro taller.
    await create(client, other.headers)


# --- Límite (§10) -------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_catalog_has_a_limit_that_counts_archived_parts(
    client: AsyncClient, admin: AdminSession
) -> None:
    await set_limit(admin.invited.workshop_id, Resource.PARTS, 1)
    part = await create(client, admin.headers)
    await client.post(
        f"{URL}/{part['id']}/archive", json={"version": 1}, headers=admin.headers
    )
    response = await client.post(
        URL, json={**BATTERY, "reference": "OTRA"}, headers=admin.headers
    )
    refused(response, "part_limit_reached")
