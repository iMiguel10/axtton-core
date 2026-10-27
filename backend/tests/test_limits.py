"""Los límites de recursos de cada taller (especificación §10, RF-114).

Que cada alta se pare en su límite con su 409, que las órdenes se cuenten por mes
del taller, que reactivar una ficha no sirva para saltárselo, y que el
superadministrador los cambie y quede en su auditoría. Las altas simultáneas con
un solo hueco están en test_concurrency.py.
"""

import os
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.domain.limits import BASIC_PLAN, Resource, limit_column
from app.infra.email import InMemoryEmailSender
from app.scripts.reset_data import truncate_all
from tests.conftest import Account, Engines
from tests.test_clients import create as create_client
from tests.test_employees import add_mechanic, invite_and_accept
from tests.test_invitations import sign_in
from tests.test_work_orders import URL as ORDERS
from tests.test_work_orders import Shop, new_shop, open_order, outbox

__all__ = ["outbox"]

MakeAccount = Callable[[str], Awaitable[Account]]


@pytest_asyncio.fixture
async def shop(client: AsyncClient) -> Shop:
    return await new_shop(client)


async def set_limit(workshop_id: str, resource: Resource, value: int) -> None:
    """Como lo haría el superadministrador, sin pasar por su API."""
    engine = create_async_engine(os.environ["PLATFORM_DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    f"UPDATE workshops SET {limit_column(resource)} = :v WHERE id = :w"
                ),
                {"v": value, "w": workshop_id},
            )
    finally:
        await engine.dispose()


def refused(response: Any, code: str) -> None:
    assert (response.status_code, response.json()) == (409, {"code": code}), (
        response.text
    )


@pytest.mark.asyncio
async def test_a_new_workshop_starts_with_the_basic_plan(
    engines: Engines, shop: Shop
) -> None:
    """Los valores por defecto de la migración son los de domain/limits.py: si
    alguien cambia uno y no el otro, esto falla."""
    async with engines.platform.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT "
                    + ", ".join(limit_column(r) for r in Resource)
                    + " FROM workshops WHERE id = :w"
                ),
                {"w": shop.admin.invited.workshop_id},
            )
        ).one()
    assert dict(zip(Resource, row, strict=True)) == BASIC_PLAN


@pytest.mark.asyncio
async def test_clients_and_vehicles_stop_at_their_limit(
    client: AsyncClient, shop: Shop
) -> None:
    """La tienda ya tiene a María y a Luis, y el coche de María."""
    workshop_id = shop.admin.invited.workshop_id
    await set_limit(workshop_id, Resource.CLIENTS, 2)
    await set_limit(workshop_id, Resource.VEHICLES, 1)

    third = await client.post(
        "/api/v1/workshop/clients",
        json={"name": "Rosa", "phone": "622"},
        headers=shop.headers,
    )
    refused(third, "client_limit_reached")
    second_car = await client.post(
        "/api/v1/workshop/vehicles",
        json={"plate": "9999 ZZZ", "owner_id": shop.luis["id"]},
        headers=shop.headers,
    )
    refused(second_car, "vehicle_limit_reached")

    # Con hueco otra vez, se puede.
    await set_limit(workshop_id, Resource.CLIENTS, 3)
    await create_client(client, shop.headers, name="Rosa", phone="622")


@pytest.mark.asyncio
async def test_archived_and_anonymized_clients_still_count(
    client: AsyncClient, shop: Shop
) -> None:
    """Si archivar liberase hueco, archivar y desarchivar serviría para saltarse
    el límite (domain/limits.py)."""
    workshop_id = shop.admin.invited.workshop_id
    await set_limit(workshop_id, Resource.CLIENTS, 2)
    luis = shop.luis
    await client.post(
        f"/api/v1/workshop/clients/{luis['id']}/archive",
        json={"version": luis["version"]},
        headers=shop.headers,
    )
    refused(
        await client.post(
            "/api/v1/workshop/clients",
            json={"name": "Rosa", "phone": "622"},
            headers=shop.headers,
        ),
        "client_limit_reached",
    )


@pytest.mark.asyncio
async def test_orders_are_limited_per_month_of_the_workshop(
    client: AsyncClient, engines: Engines, shop: Shop
) -> None:
    workshop_id = shop.admin.invited.workshop_id
    await set_limit(workshop_id, Resource.ORDERS_PER_MONTH, 1)
    first = await open_order(client, shop.headers, shop.car["id"])
    second = await client.post(
        ORDERS,
        json={"vehicle_id": shop.car["id"], "type": "other"},
        headers=shop.headers,
    )
    refused(second, "order_limit_reached")

    # La de antes de este mes ya no cuenta: el contador vuelve a empezar.
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "UPDATE work_orders SET created_at = date_trunc('month', now())"
                " - interval '1 day' WHERE id = :o"
            ),
            {"o": first["id"]},
        )
    await open_order(client, shop.headers, shop.car["id"])


@pytest.mark.asyncio
async def test_employee_records_stop_at_their_limit_even_when_reactivating(
    client: AsyncClient, shop: Shop
) -> None:
    """La administradora ya es una ficha. Con límite 2 cabe Juan y no Pedro; y
    desactivar a Juan, dar de alta a Pedro y reactivar a Juan dejaría tres."""
    workshop_id = shop.admin.invited.workshop_id
    await set_limit(workshop_id, Resource.EMPLOYEES, 2)
    juan = await add_mechanic(client, shop.admin, "Juan")
    refused(
        await client.post(
            "/api/v1/workshop/employees",
            json={"name": "Pedro", "role": "mechanic"},
            headers=shop.headers,
        ),
        "employee_record_limit_reached",
    )

    await client.patch(
        f"/api/v1/workshop/employees/{juan}",
        json={"version": 1, "active": False},
        headers=shop.headers,
    )
    await add_mechanic(client, shop.admin, "Pedro")
    reactivate = await client.patch(
        f"/api/v1/workshop/employees/{juan}",
        json={"version": 2, "active": True},
        headers=shop.headers,
    )
    refused(reactivate, "employee_record_limit_reached")


@pytest.mark.asyncio
async def test_reactivating_someone_with_access_respects_the_access_limit(
    client: AsyncClient, shop: Shop, outbox: InMemoryEmailSender
) -> None:
    """El hueco que se abrió en F1: el límite de acceso solo se miraba al aceptar
    una invitación. Desactivar a quien tiene acceso, dar acceso a otro y
    reactivar al primero dejaba el taller por encima."""
    workshop_id = shop.admin.invited.workshop_id
    juan = await add_mechanic(client, shop.admin, "Juan")
    await invite_and_accept(client, shop.admin, outbox, juan)
    await set_limit(workshop_id, Resource.EMPLOYEES_WITH_ACCESS, 2)

    await client.patch(
        f"/api/v1/workshop/employees/{juan}",
        json={"version": 2, "active": False},
        headers=shop.headers,
    )
    pedro = await add_mechanic(client, shop.admin, "Pedro")
    await invite_and_accept(client, shop.admin, outbox, pedro)
    reactivate = await client.patch(
        f"/api/v1/workshop/employees/{juan}",
        json={"version": 3, "active": True},
        headers=shop.headers,
    )
    refused(reactivate, "employee_limit_reached")


@pytest.mark.asyncio
async def test_the_admin_sees_the_usage_and_the_mechanic_does_not(
    client: AsyncClient, shop: Shop, outbox: InMemoryEmailSender
) -> None:
    await open_order(client, shop.headers, shop.car["id"])
    usage = await client.get("/api/v1/workshop/limits", headers=shop.headers)
    assert usage.status_code == 200
    assert {u["resource"]: (u["used"], u["limit"]) for u in usage.json()} == {
        "employees_with_access": (1, 5),
        "employees": (1, 10),
        "clients": (2, 1000),
        "vehicles": (1, 1500),
        "orders_per_month": (1, 200),
    }
    mechanic = await invite_and_accept(
        client, shop.admin, outbox, await add_mechanic(client, shop.admin)
    )
    forbidden = await client.get("/api/v1/workshop/limits", headers=mechanic)
    assert (forbidden.status_code, forbidden.json()) == (403, {"code": "not_allowed"})


# --- El superadministrador (RF-114) ------------------------------------------


@pytest.mark.asyncio
async def test_the_superadmin_changes_limits_and_it_is_audited(
    client: AsyncClient,
    engines: Engines,
    make_account: MakeAccount,
    outbox: InMemoryEmailSender,
) -> None:
    await truncate_all()
    headers = {
        "Authorization": f"Bearer {await sign_in(client, await make_account('superadmin'))}"
    }
    created = await client.post(
        "/api/v1/admin/workshops",
        json={
            "name": "Taller Norte",
            "admin_name": "Ana",
            "admin_email": "ana@norte.example.com",
        },
        headers=headers,
    )
    workshop_id = created.json()["workshop_id"]

    changed = await client.patch(
        f"/api/v1/admin/workshops/{workshop_id}",
        json={"limits": {"clients": 50, "orders_per_month": 20, "vehicles": 1500}},
        headers=headers,
    )
    assert changed.status_code == 204, changed.text
    [workshop] = (await client.get("/api/v1/admin/workshops", headers=headers)).json()
    assert {u["resource"]: (u["used"], u["limit"]) for u in workshop["limits"]} == {
        "employees_with_access": (0, 5),
        # La ficha de Ana, aún sin aceptar la invitación.
        "employees": (1, 10),
        "clients": (0, 50),
        "vehicles": (0, 1500),
        "orders_per_month": (0, 20),
    }
    async with engines.platform.connect() as conn:
        details = await conn.scalar(
            text(
                "SELECT details FROM audit_log WHERE action = 'workshop_updated'"
                " AND target_id = :w"
            ),
            {"w": UUID(workshop_id)},
        )
    # Solo lo que cambió: los vehículos ya estaban en 1500.
    assert details == {"max_clients": [1000, 50], "max_orders_per_month": [200, 20]}

    for bad in ({"clients": 0}, {"clients": 2_000_000}, {"unknown": 5}):
        response = await client.patch(
            f"/api/v1/admin/workshops/{workshop_id}",
            json={"limits": bad},
            headers=headers,
        )
        assert response.status_code == 422, bad


@pytest.mark.asyncio
async def test_a_workshop_cannot_change_its_own_limits(
    engines: Engines, shop: Shop
) -> None:
    """Solo la plataforma escribe en `workshops` (migración 0003grants)."""
    from sqlalchemy.exc import DBAPIError

    from tests.test_rls import set_workshops

    with pytest.raises(DBAPIError, match="permission denied"):
        async with engines.app.begin() as conn:
            await set_workshops(conn, UUID(shop.admin.invited.workshop_id))
            await conn.execute(text("UPDATE workshops SET max_clients = 1000000"))
