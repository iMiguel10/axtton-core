"""El informe de actuaciones de un vehículo (F6 paso 5: RF-18, RNF-16, RNF-52).

El coche de María pasa por el taller (diagnóstico, presupuesto aprobado con una
pieza, un trabajo y otro anulado, entrega con sus km), se vende a Luis y vuelve
con él. Una orden cancelada no aparece.
"""

import os
import time
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.infra.email import InMemoryEmailSender
from tests.test_anonymize import anonymize, read
from tests.test_clients import create as create_client
from tests.test_clients import open_workshop
from tests.test_delivery_summary import deliver, repaired_and_ready
from tests.test_employees import add_mechanic, invite_and_accept
from tests.test_quote_pdf import text_of
from tests.test_reception import audit_actions
from tests.test_vehicles import change_owner
from tests.test_vehicles import create as create_vehicle
from tests.test_vehicles import get as get_vehicle
from tests.test_work_orders import URL, Shop, get, new_shop, open_order, outbox, shop
from tests.test_worklog import diagnose

__all__ = ["outbox", "shop"]

VEHICLES = "/api/v1/workshop/vehicles"


async def report(
    client: AsyncClient, headers: dict[str, str], vehicle_id: str, **params: Any
) -> Response:
    return await client.get(
        f"{VEHICLES}/{vehicle_id}/report/pdf", params=params, headers=headers
    )


async def car(client: AsyncClient, shop: Shop) -> Any:
    return await get_vehicle(client, shop.headers, shop.car["id"])


async def two_owners(client: AsyncClient, shop: Shop) -> tuple[str, str]:
    """La orden entregada de María y, vendido el coche a Luis, la abierta de Luis.
    Entre medias, una de María cancelada."""
    first = await repaired_and_ready(client, shop)
    assert (await deliver(client, shop, first, odometer_km=187_423)).status_code == 204
    cancelled = await open_order(client, shop.headers, shop.car["id"])
    response = await client.post(
        f"{URL}/{cancelled['id']}/status",
        json={
            "version": cancelled["version"],
            "to_status": "cancelled",
            "note": "Abierta por error",
        },
        headers=shop.headers,
    )
    assert response.status_code == 204, response.text
    moved = await change_owner(
        client, shop.headers, await car(client, shop), shop.luis["id"]
    )
    assert moved.status_code == 204, moved.text
    second = await open_order(client, shop.headers, shop.car["id"], odometer_km=195_000)
    written = await diagnose(
        client, shop.headers, second["id"], 0, "Ruido en la suspensión trasera"
    )
    assert written.status_code == 201, written.text
    return first, second["id"]


@pytest.mark.asyncio
async def test_rf18_every_order_of_every_owner_without_names_or_amounts(
    client: AsyncClient, shop: Shop
) -> None:
    first, second = await two_owners(client, shop)
    response = await report(client, shop.headers, shop.car["id"])
    assert response.headers["cache-control"] == "no-store"
    assert "informe-de-actuaciones-" in response.headers["content-disposition"]
    content = text_of(response)
    first_code = (await get(client, shop.headers, first))["code"]
    second_code = (await get(client, shop.headers, second))["code"]
    for expected in (
        "Informe de actuaciones",
        shop.car["plate"],
        "2 órdenes",
        first_code,
        second_code,
        # Km de cada visita y de la entrega.
        "187.410 km",
        "187.423 km",
        "195.000 km",
        # Diagnóstico, trabajos y piezas de la primera; la segunda, en curso.
        "Cambio de pastillas delanteras",
        "Pastillas de freno delanteras",
        "Ref. BP-1234",
        "Ruido en la suspensión trasera",
        "En curso",
        "No incluye los nombres de sus titulares",
        "No incluye importes",
    ):
        assert expected in content, expected
    # La primera, antes que la segunda.
    assert content.index(first_code) < content.index(second_code)
    for absent in ("María", "Luis", "€", "Anotado por error"):
        assert absent not in content, absent
    # Sin datos personales, no queda en la auditoría.
    actions = [e["action"] for e in await audit_actions(client, shop.headers)]
    assert "vehicle_report_extended" not in actions


@pytest.mark.asyncio
async def test_the_admin_can_add_owners_and_amounts_and_it_is_audited(
    client: AsyncClient, shop: Shop
) -> None:
    await two_owners(client, shop)
    content = text_of(await report(client, shop.headers, shop.car["id"], owners=True))
    assert "Cliente: María" in content and "Cliente: Luis" in content
    assert "€" not in content

    content = text_of(await report(client, shop.headers, shop.car["id"], amounts=True))
    assert "Importe del presupuesto aceptado" in content
    assert "María" not in content

    extended = [
        e
        for e in await audit_actions(client, shop.headers)
        if e["action"] == "vehicle_report_extended"
    ]
    assert [e["details"] for e in extended] == [
        {"owners": False, "amounts": True},
        {"owners": True, "amounts": False},
    ]
    assert {e["target_type"] for e in extended} == {"vehicle"}


@pytest.mark.asyncio
async def test_an_anonymized_owner_is_a_deleted_client(
    client: AsyncClient, shop: Shop
) -> None:
    await two_owners(client, shop)
    maria = await read(client, shop.headers, shop.maria["id"])
    assert (await anonymize(client, shop.headers, maria)).status_code == 204
    content = text_of(await report(client, shop.headers, shop.car["id"], owners=True))
    assert "Cliente: Cliente eliminado" in content
    assert "María" not in content


@pytest.mark.asyncio
async def test_a_mechanic_gets_the_basic_report_only(
    client: AsyncClient, shop: Shop, outbox: InMemoryEmailSender
) -> None:
    await two_owners(client, shop)
    mechanic = await invite_and_accept(
        client, shop.admin, outbox, await add_mechanic(client, shop.admin, "Pepe")
    )
    assert (await report(client, mechanic, shop.car["id"])).status_code == 200
    for params in ({"owners": True}, {"amounts": True}):
        refused = await report(client, mechanic, shop.car["id"], **params)
        assert refused.status_code == 403, params
        assert refused.json()["code"] == "vehicle_report_extended_forbidden"


@pytest.mark.asyncio
async def test_a_vehicle_without_orders_and_one_of_another_workshop(
    client: AsyncClient, shop: Shop
) -> None:
    content = text_of(await report(client, shop.headers, shop.car["id"]))
    assert "no tiene ninguna orden" in content
    other = await new_shop_keeping(client)
    missing = await report(client, other.headers, shop.car["id"])
    assert missing.status_code == 404
    assert missing.json()["code"] == "vehicle_not_found"


async def new_shop_keeping(client: AsyncClient) -> Shop:
    """Otro taller sin vaciar la base de datos (new_shop la vacía)."""
    admin = await open_workshop(client, "Talleres Norte")
    maria = await create_client(client, admin.headers, name="María Norte")
    luis = await create_client(client, admin.headers, name="Luis Norte", phone="622")
    car = await create_vehicle(client, admin.headers, maria["id"], make="Seat")
    return Shop(admin, maria, luis, car)


# --- RNF-52: cien órdenes en menos de 10 s ----------------------------------------


async def hundred_orders(client: AsyncClient, shop: Shop) -> None:
    """Cien órdenes del mismo coche, abiertas por la API; su diagnóstico y tres
    trabajos por orden, escritos de una vez con el rol de plataforma."""
    for _ in range(100):
        response = await client.post(
            URL,
            json={"vehicle_id": shop.car["id"], "type": "maintenance"},
            headers=shop.headers,
        )
        assert response.status_code == 201, response.text
    engine = create_async_engine(os.environ["PLATFORM_DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO diagnosis_versions"
                    " (workshop_id, work_order_id, version_no, text, employee_id)"
                    " SELECT o.workshop_id, o.id, 1, :text, e.id"
                    " FROM work_orders o JOIN employees e"
                    " ON e.workshop_id = o.workshop_id"
                    " WHERE o.vehicle_id = :v"
                ),
                {"v": shop.car["id"], "text": "Revisión de los 15.000 km. " * 12},
            )
            await conn.execute(
                text(
                    "INSERT INTO work_entries (workshop_id, work_order_id,"
                    " employee_id, recorded_by_employee_id, description, worked_on)"
                    " SELECT o.workshop_id, o.id, e.id, e.id,"
                    " 'Cambio de aceite y filtros ' || n, current_date"
                    " FROM work_orders o JOIN employees e"
                    " ON e.workshop_id = o.workshop_id,"
                    " generate_series(1, 3) AS n WHERE o.vehicle_id = :v"
                ),
                {"v": shop.car["id"]},
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rnf52_a_hundred_orders_in_less_than_ten_seconds(
    client: AsyncClient,
) -> None:
    shop = await new_shop(client)
    await hundred_orders(client, shop)
    started = time.monotonic()
    content = text_of(await report(client, shop.headers, shop.car["id"]))
    elapsed = time.monotonic() - started
    assert "100 órdenes" in content
    assert content.count("Cambio de aceite y filtros") == 300
    assert elapsed < 10, f"{elapsed:.1f} s"
