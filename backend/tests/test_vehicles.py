"""Vehículos y titularidad por la API (RF-11 a RF-13, RNF-01, RNF-15, RNF-16).

Las restricciones de la base de datos sobre los periodos (dos titulares a la
vez, periodos solapados, periodos cerrados) están en test_ownerships_db.py, y el
cambio de titular simultáneo en test_concurrency.py.
"""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.api.deps import get_email_sender
from app.infra.email import InMemoryEmailSender
from app.main import app
from app.scripts.reset_data import truncate_all
from tests.test_clients import create as create_client
from tests.test_clients import open_workshop
from tests.test_employees import AdminSession, add_mechanic, invite_and_accept

URL = "/api/v1/workshop/vehicles"


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


@pytest_asyncio.fixture
async def maria(client: AsyncClient, admin: AdminSession) -> dict[str, Any]:
    return await create_client(client, admin.headers, name="María")


@pytest_asyncio.fixture
async def luis(client: AsyncClient, admin: AdminSession) -> dict[str, Any]:
    return await create_client(client, admin.headers, name="Luis", phone="611")


async def create(
    client: AsyncClient, headers: dict[str, str], owner_id: str, **fields: Any
) -> dict[str, Any]:
    body = {"plate": "1234 BCD", "owner_id": owner_id, **fields}
    response = await client.post(URL, json=body, headers=headers)
    assert response.status_code == 201, response.text
    return await get(client, headers, response.json()["id"])


async def get(client: AsyncClient, headers: dict[str, str], vehicle_id: str) -> Any:
    response = await client.get(f"{URL}/{vehicle_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def change_owner(
    client: AsyncClient, headers: dict[str, str], vehicle: dict[str, Any], to: str
) -> Any:
    return await client.post(
        f"{URL}/{vehicle['id']}/owner",
        json={"version": vehicle["version"], "client_id": to},
        headers=headers,
    )


# --- Alta y ficha ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_vehicle_is_born_with_its_owner_and_a_normalized_plate(
    client: AsyncClient, admin: AdminSession, maria: dict[str, Any]
) -> None:
    car = await create(
        client,
        admin.headers,
        maria["id"],
        plate=" 1234-bcd ",
        vin="vf1 rfb0 0123 4567 89",
        make="Renault",
        model="Clio",
        year=2019,
        fuel="diesel",
        next_itv_date="2027-03-01",
    )
    # Lo escrito se conserva para mostrarlo; la normalizada es la que es única.
    assert (car["plate"], car["plate_normalized"]) == ("1234-bcd", "1234BCD")
    assert car["vin"] == "VF1RFB00123456789"
    assert car["owner"] == {"id": maria["id"], "name": "María"}
    [period] = car["ownerships"]
    assert (period["client"]["id"], period["ended_at"]) == (maria["id"], None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"plate": "¡¡!!"}, "invalid_plate"),
        ({"plate": " - "}, "invalid_plate"),
        ({"vin": "VF1-ÑÑ"}, "invalid_vin"),
    ],
)
async def test_an_impossible_plate_or_vin_is_a_422_with_its_code(
    client: AsyncClient,
    admin: AdminSession,
    maria: dict[str, Any],
    fields: dict[str, str],
    code: str,
) -> None:
    response = await client.post(
        URL,
        json={"plate": "1234BCD", "owner_id": maria["id"], **fields},
        headers=admin.headers,
    )
    assert (response.status_code, response.json()) == (422, {"code": code})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields",
    [{"year": 1800}, {"fuel": "carbón"}, {"next_service_km": 0}, {"plate": ""}],
)
async def test_invalid_fields_are_a_422(
    client: AsyncClient,
    admin: AdminSession,
    maria: dict[str, Any],
    fields: dict[str, Any],
) -> None:
    response = await client.post(
        URL,
        json={"plate": "1234BCD", "owner_id": maria["id"], **fields},
        headers=admin.headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_vehicle_needs_an_owner(
    client: AsyncClient, admin: AdminSession
) -> None:
    response = await client.post(URL, json={"plate": "1"}, headers=admin.headers)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_an_archived_client_cannot_receive_a_vehicle(
    client: AsyncClient, admin: AdminSession, maria: dict[str, Any], luis: dict
) -> None:
    await client.post(
        f"/api/v1/workshop/clients/{luis['id']}/archive",
        json={"version": luis["version"]},
        headers=admin.headers,
    )
    response = await client.post(
        URL, json={"plate": "1", "owner_id": luis["id"]}, headers=admin.headers
    )
    assert (response.status_code, response.json()) == (409, {"code": "client_archived"})
    car = await create(client, admin.headers, maria["id"])
    moved = await change_owner(client, admin.headers, car, luis["id"])
    assert (moved.status_code, moved.json()) == (409, {"code": "client_archived"})


@pytest.mark.asyncio
async def test_the_plate_and_the_vin_are_unique_in_the_workshop(
    client: AsyncClient, admin: AdminSession, maria: dict[str, Any]
) -> None:
    first = await create(client, admin.headers, maria["id"], vin="VF1AAA")
    for fields, code in (
        ({"plate": "1234-BCD"}, "vehicle_plate_taken"),
        ({"plate": "9999XYZ", "vin": "vf1aaa"}, "vehicle_vin_taken"),
    ):
        response = await client.post(
            URL, json={"owner_id": maria["id"], **fields}, headers=admin.headers
        )
        assert (response.status_code, response.json()) == (409, {"code": code})

    other = await create(client, admin.headers, maria["id"], plate="5678 CDF")
    clash = await client.patch(
        f"{URL}/{other['id']}",
        json={"version": other["version"], "plate": "1234bcd"},
        headers=admin.headers,
    )
    assert (clash.status_code, clash.json()) == (409, {"code": "vehicle_plate_taken"})
    # Guardar la propia matrícula, escrita de otra forma, no choca consigo misma.
    same = await client.patch(
        f"{URL}/{first['id']}",
        json={"version": first["version"], "plate": "1234-bcd", "vin": "VF1AAA"},
        headers=admin.headers,
    )
    assert same.status_code == 204


# --- Listado, búsqueda y sugerencias ----------------------------------------


@pytest.mark.asyncio
async def test_the_list_shows_the_current_owner_and_finds_plates_however_written(
    client: AsyncClient, admin: AdminSession, maria: dict, luis: dict
) -> None:
    await create(client, admin.headers, maria["id"], plate="1234BCD", make="Seat")
    await create(client, admin.headers, luis["id"], plate="5678 CDF", make="Renault")

    listed = (await client.get(URL, headers=admin.headers)).json()
    assert [(v["plate_normalized"], v["owner"]["name"]) for v in listed] == [
        ("1234BCD", "María"),
        ("5678CDF", "Luis"),
    ]
    for q in ("5678-cdf", "78 c", "renau"):
        found = await client.get(URL, params={"q": q}, headers=admin.headers)
        assert [v["plate_normalized"] for v in found.json()] == ["5678CDF"], q

    of_luis = await client.get(
        URL, params={"owner_id": luis["id"]}, headers=admin.headers
    )
    assert [v["plate_normalized"] for v in of_luis.json()] == ["5678CDF"]


@pytest.mark.asyncio
async def test_suggestions_are_what_the_workshop_already_wrote(
    client: AsyncClient, admin: AdminSession, maria: dict[str, Any]
) -> None:
    for n, (make, model) in enumerate(
        [("Seat", "Ibiza"), ("Seat", "León"), ("Seat", "Ibiza"), ("Renault", "Clio")]
    ):
        await create(
            client, admin.headers, maria["id"], plate=f"{n}AAA", make=make, model=model
        )

    async def suggest(**params: str) -> list[str]:
        response = await client.get(
            f"{URL}/suggestions", params=params, headers=admin.headers
        )
        assert response.status_code == 200
        result: list[str] = response.json()
        return result

    # Lo más usado primero.
    assert await suggest(field="make") == ["Seat", "Renault"]
    assert await suggest(field="make", q="re") == ["Renault"]
    assert await suggest(field="model", make="seat") == ["Ibiza", "León"]


# --- Edición -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_editing_a_vehicle_with_an_old_version_is_a_409(
    client: AsyncClient, admin: AdminSession, maria: dict[str, Any]
) -> None:
    car = await create(client, admin.headers, maria["id"])
    first = await client.patch(
        f"{URL}/{car['id']}",
        json={"version": car["version"], "next_service_km": 90000},
        headers=admin.headers,
    )
    second = await client.patch(
        f"{URL}/{car['id']}",
        json={"version": car["version"], "model": "Otro"},
        headers=admin.headers,
    )
    assert (first.status_code, second.status_code) == (204, 409)
    assert (await get(client, admin.headers, car["id"]))["next_service_km"] == 90000


@pytest.mark.asyncio
async def test_the_plate_cannot_be_nulled(
    client: AsyncClient, admin: AdminSession, maria: dict[str, Any]
) -> None:
    car = await create(client, admin.headers, maria["id"])
    response = await client.patch(
        f"{URL}/{car['id']}",
        json={"version": car["version"], "plate": None},
        headers=admin.headers,
    )
    assert response.status_code == 422


# --- Cambio de titular (RF-12) ----------------------------------------------


@pytest.mark.asyncio
async def test_changing_the_owner_closes_one_period_and_opens_the_next(
    client: AsyncClient, admin: AdminSession, maria: dict, luis: dict
) -> None:
    car = await create(client, admin.headers, maria["id"])
    response = await change_owner(client, admin.headers, car, luis["id"])
    assert response.status_code == 204

    after = await get(client, admin.headers, car["id"])
    assert after["owner"]["name"] == "Luis"
    new, old = after["ownerships"]
    assert (new["client"]["name"], new["ended_at"]) == ("Luis", None)
    assert old["client"]["name"] == "María"
    # Sin hueco ni solape: el anterior acaba en el instante en que empieza el nuevo.
    assert datetime.fromisoformat(old["ended_at"]) == datetime.fromisoformat(
        new["started_at"]
    )
    # El titular es parte de la ficha: quien la tuviera abierta ya no la pisa.
    assert after["version"] == car["version"] + 1
    stale = await client.patch(
        f"{URL}/{car['id']}",
        json={"version": car["version"], "model": "X"},
        headers=admin.headers,
    )
    assert stale.status_code == 409

    # El anterior deja de ser titular: sus vehículos actuales ya no lo incluyen.
    of_maria = await client.get(
        URL, params={"owner_id": maria["id"]}, headers=admin.headers
    )
    assert of_maria.json() == []


@pytest.mark.asyncio
async def test_an_old_owner_can_be_the_owner_again(
    client: AsyncClient, admin: AdminSession, maria: dict, luis: dict
) -> None:
    car = await create(client, admin.headers, maria["id"])
    await change_owner(client, admin.headers, car, luis["id"])
    car = await get(client, admin.headers, car["id"])
    assert (
        await change_owner(client, admin.headers, car, maria["id"])
    ).status_code == 204
    after = await get(client, admin.headers, car["id"])
    assert [o["client"]["name"] for o in after["ownerships"]] == [
        "María",
        "Luis",
        "María",
    ]


@pytest.mark.asyncio
async def test_giving_the_vehicle_to_its_current_owner_changes_nothing(
    client: AsyncClient, admin: AdminSession, maria: dict[str, Any]
) -> None:
    car = await create(client, admin.headers, maria["id"])
    assert (
        await change_owner(client, admin.headers, car, maria["id"])
    ).status_code == 204
    after = await get(client, admin.headers, car["id"])
    assert (len(after["ownerships"]), after["version"]) == (1, car["version"])


@pytest.mark.asyncio
async def test_changing_the_owner_with_an_old_version_is_a_409(
    client: AsyncClient, admin: AdminSession, maria: dict, luis: dict
) -> None:
    car = await create(client, admin.headers, maria["id"])
    await client.patch(
        f"{URL}/{car['id']}",
        json={"version": car["version"], "model": "Clio"},
        headers=admin.headers,
    )
    response = await change_owner(client, admin.headers, car, luis["id"])
    assert (response.status_code, response.json()) == (
        409,
        {"code": "modified_by_someone_else"},
    )
    assert len((await get(client, admin.headers, car["id"]))["ownerships"]) == 1


@pytest.mark.asyncio
async def test_an_owner_change_is_audited_with_names_read_at_query_time(
    client: AsyncClient, admin: AdminSession, maria: dict, luis: dict
) -> None:
    """RNF-16. El registro guarda ids; los nombres se ponen al leerlo, así que
    un cliente renombrado (o anonimizado, RF-15) aparece como es hoy."""
    car = await create(client, admin.headers, maria["id"])
    await change_owner(client, admin.headers, car, luis["id"])
    await client.patch(
        f"/api/v1/workshop/clients/{luis['id']}",
        json={"version": luis["version"], "name": "Luis Ruiz"},
        headers=admin.headers,
    )

    audit = await client.get("/api/v1/workshop/audit", headers=admin.headers)
    entry = next(
        e for e in audit.json()["entries"] if e["action"] == "vehicle_owner_changed"
    )
    assert entry["target_name"] == "1234 BCD"
    assert entry["details"] == {"client_id": ["María", "Luis Ruiz"]}
    assert entry["actor"] == "Ana López"


# --- Permisos (especificación §3) -------------------------------------------


@pytest.mark.asyncio
async def test_a_mechanic_sees_vehicles_but_cannot_change_them(
    client: AsyncClient,
    admin: AdminSession,
    outbox: InMemoryEmailSender,
    maria: dict,
    luis: dict,
) -> None:
    mechanic = await invite_and_accept(
        client, admin, outbox, await add_mechanic(client, admin)
    )
    car = await create(client, admin.headers, maria["id"])

    assert (await client.get(URL, headers=mechanic)).status_code == 200
    assert (await client.get(f"{URL}/{car['id']}", headers=mechanic)).status_code == 200
    suggestions = await client.get(
        f"{URL}/suggestions", params={"field": "make"}, headers=mechanic
    )
    assert suggestions.status_code == 200

    for response in (
        await client.post(
            URL, json={"plate": "1", "owner_id": maria["id"]}, headers=mechanic
        ),
        await client.patch(
            f"{URL}/{car['id']}",
            json={"version": car["version"], "model": "X"},
            headers=mechanic,
        ),
        await change_owner(client, mechanic, car, luis["id"]),
    ):
        assert (response.status_code, response.json()) == (
            403,
            {"code": "not_allowed"},
        )
    assert (await get(client, admin.headers, car["id"]))["version"] == car["version"]


# --- Aislamiento entre talleres (RNF-01, RNF-07) ----------------------------


@pytest.mark.asyncio
async def test_vehicles_and_clients_of_another_workshop_do_not_exist(
    client: AsyncClient, admin: AdminSession, maria: dict[str, Any]
) -> None:
    car = await create(client, admin.headers, maria["id"], make="Seat")
    b = (await open_workshop(client, "Taller B")).headers
    ana_b = await create_client(client, b, name="Ana de B")

    version = {"version": car["version"]}
    for response in (
        await client.get(f"{URL}/{car['id']}", headers=b),
        await client.patch(
            f"{URL}/{car['id']}", json={**version, "model": "X"}, headers=b
        ),
        await change_owner(client, b, car, ana_b["id"]),
    ):
        assert (response.status_code, response.json()) == (
            404,
            {"code": "vehicle_not_found"},
        )
    assert (await client.get(URL, headers=b)).json() == []
    suggestions = await client.get(
        f"{URL}/suggestions", params={"field": "make"}, headers=b
    )
    assert suggestions.json() == []

    # Desde A, un cliente de B no existe: ni para darle un vehículo ni para
    # pasarle uno (y la FK compuesta lo impediría aunque el código fallara).
    stolen = await change_owner(client, admin.headers, car, ana_b["id"])
    assert (stolen.status_code, stolen.json()) == (404, {"code": "client_not_found"})
    created = await client.post(
        URL, json={"plate": "1", "owner_id": ana_b["id"]}, headers=admin.headers
    )
    assert (created.status_code, created.json()) == (404, {"code": "client_not_found"})

    # La matrícula es única por taller: en B, el mismo coche es otro vehículo.
    await create(client, b, ana_b["id"])
    assert (await get(client, admin.headers, car["id"]))["owner"]["name"] == "María"
