"""Los datos de demostración (app/scripts/seed_demo.py).

La demo desplegada lo ejecuta cada noche: tiene que poder repetirse, dejar
datos que cumplan las reglas y negarse a correr donde no debe.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.scripts import seed_demo
from tests.conftest import Engines
from tests.test_invitations import bearer

# La de la demo, no otra: el core de SuperTokens es el mismo en desarrollo y en
# las pruebas, y con otra contraseña las cuentas de tu demo local dejarían de
# entrar después de pasar las pruebas.
PASSWORD = seed_demo.DEFAULT_PASSWORD


async def as_laura(client: AsyncClient, workshop: str) -> dict[str, str]:
    headers = await bearer(client, "laura@demo.example.com", PASSWORD)
    me = (await client.get("/api/v1/workshop/me", headers=headers)).json()
    [chosen] = [w for w in me["workshops"] if w["workshop_name"] == workshop]
    return {**headers, "X-Workshop-Id": chosen["workshop_id"]}


def test_it_refuses_to_run_without_being_enabled() -> None:
    """Borra todo: sin DEMO_SEED_ENABLED, ni lo intenta."""
    with pytest.raises(SystemExit, match="DEMO_SEED_ENABLED"):
        seed_demo.main([])


@pytest.mark.asyncio
async def test_it_can_run_every_night_and_leaves_a_working_demo(
    client: AsyncClient, engines: Engines
) -> None:
    # Dos veces: la segunda reutiliza las cuentas de SuperTokens.
    for _ in range(2):
        await seed_demo.seed_demo(password=PASSWORD)

    # Laura entra con la contraseña de la demo y ve sus dos talleres.
    main = await as_laura(client, "Talleres Martínez")
    me = (await client.get("/api/v1/workshop/me", headers=main)).json()
    assert sorted(w["workshop_name"] for w in me["workshops"]) == [
        "Taller Rápido Levante",
        "Talleres Martínez",
    ]

    orders: list[dict[str, Any]] = (
        await client.get(
            "/api/v1/workshop/orders",
            params={"state": "all", "limit": 100},
            headers=main,
        )
    ).json()
    # Numeradas por fecha: la más antigua es la 1.
    by_number = sorted(orders, key=lambda o: o["number"])
    assert [o["created_at"] for o in by_number] == sorted(
        o["created_at"] for o in orders
    )
    assert {o["status"] for o in orders} >= {
        "received",
        "diagnosing",
        "in_repair",
        "waiting_parts",
        "ready",
        "delivered",
        "cancelled",
    }

    unpaid = (await client.get("/api/v1/workshop/orders/unpaid", headers=main)).json()
    assert [o["days_pending"] for o in unpaid] == [19, 3]

    # La siguiente orden sigue la serie.
    car = next(o for o in orders if o["status"] == "received")["vehicle"]["id"]
    opened = await client.post(
        "/api/v1/workshop/orders",
        json={"vehicle_id": car, "type": "other"},
        headers=main,
    )
    assert opened.json()["code"].endswith(f"-{len(orders) + 1:04d}"), opened.text

    async with engines.platform.connect() as conn:
        anonymized = await conn.scalar(
            text("SELECT count(*) FROM clients WHERE anonymized_at IS NOT NULL")
        )
        # El periodo de titularidad congelado se reactivó al terminar.
        trigger = await conn.scalar(
            text(
                "SELECT tgenabled::text FROM pg_trigger"
                " WHERE tgname = 'vehicle_ownerships_closed_frozen'"
            )
        )
    assert (anonymized, trigger) == (1, "O")


@pytest.mark.asyncio
async def test_a_mechanic_of_the_demo_sees_what_a_mechanic_sees(
    client: AsyncClient,
) -> None:
    await seed_demo.seed_demo(password=PASSWORD)
    headers = await bearer(client, "javier@demo.example.com", PASSWORD)
    me = (await client.get("/api/v1/workshop/me", headers=headers)).json()
    [membership] = me["workshops"]
    assert membership["role"] == "mechanic"
    headers["X-Workshop-Id"] = membership["workshop_id"]
    mine = await client.get(
        "/api/v1/workshop/orders", params={"mine": True}, headers=headers
    )
    assert len(mine.json()) >= 2
