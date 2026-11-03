"""Los datos de demostración (app/scripts/seed_demo.py).

La demo desplegada lo ejecuta cada noche: tiene que poder repetirse, dejar
datos que cumplan las reglas y negarse a correr donde no debe.
"""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from supertokens_python.recipe.emailpassword.asyncio import sign_up
from supertokens_python.recipe.emailpassword.interfaces import SignUpOkResult

from app.core.config import get_settings
from app.scripts import seed_demo
from tests.conftest import Account, Engines

MakeAccount = Callable[[str], Awaitable[Account]]
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


def test_it_refuses_to_run_without_being_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Borra todo: sin DEMO_SEED_ENABLED, ni lo intenta."""
    # El .env de desarrollo la trae activada: sin quitarla, la prueba ejecutaba
    # el script de verdad.
    monkeypatch.setenv("DEMO_SEED_ENABLED", "false")
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit, match="DEMO_SEED_ENABLED"):
            seed_demo.main([])
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_demo_has_no_superadmin_but_keeps_the_real_ones(
    client: AsyncClient, engines: Engines, make_account: MakeAccount
) -> None:
    """La demo es pública: un superadministrador suyo podría subir los límites o
    dar de alta talleres. El de verdad (create_superadmin) sobrevive a la recarga;
    uno del dominio de la demo (la demo lo tuvo hasta la v0.3.0), no."""
    real = await make_account("superadmin")
    old_demo = await sign_up(
        "public", f"old-{uuid4().hex[:8]}@demo.example.com", "x" * 12
    )
    assert isinstance(old_demo, SignUpOkResult)
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO users (supertokens_user_id, kind) VALUES (:s, 'superadmin')"
            ),
            {"s": old_demo.user.id},
        )

    await seed_demo.seed_demo(password=PASSWORD)

    async with engines.platform.connect() as conn:
        superadmins = set(
            (
                await conn.scalars(
                    text(
                        "SELECT supertokens_user_id FROM users WHERE kind = 'superadmin'"
                    )
                )
            ).all()
        )
    assert real.supertokens_user_id in superadmins
    assert old_demo.user.id not in superadmins
    # Y el de verdad sigue entrando en /admin con su contraseña.
    headers = await bearer(client, real.email, real.password)
    assert (
        await client.get("/api/v1/admin/workshops", headers=headers)
    ).status_code == 200


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
        "pending_approval",
        "in_repair",
        "waiting_parts",
        "ready",
        "delivered",
        "cancelled",
    }

    unpaid = (await client.get("/api/v1/workshop/orders/unpaid", headers=main)).json()
    assert [o["days_pending"] for o in unpaid] == [19, 3]
    # La de hace 19 días tiene su presupuesto aprobado: se sabe cuánto cobrar.
    assert unpaid[0]["amount_cents"] is not None

    # F3: presupuestos en cada estado, y uno enviado hace semanas, caducado.
    quotes = (
        await client.get(
            "/api/v1/workshop/quotes", params={"view": "all"}, headers=main
        )
    ).json()
    assert {q["status"] for q in quotes} >= {"draft", "sent", "approved", "rejected"}
    expired = (
        await client.get(
            "/api/v1/workshop/quotes", params={"view": "expired"}, headers=main
        )
    ).json()
    assert len(expired) == 1
    approved = next(q for q in quotes if q["status"] == "approved")
    pdf = await client.get(
        f"/api/v1/workshop/quotes/{approved['id']}/pdf", headers=main
    )
    assert pdf.status_code == 200
    rates = (await client.get("/api/v1/workshop/labor-rates", headers=main)).json()
    assert [r["is_default"] for r in rates].count(True) == 1

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
        # Y los que congelan los presupuestos enviados y sus decisiones, también.
        frozen = (
            await conn.scalars(
                text(
                    "SELECT tgenabled::text FROM pg_trigger WHERE tgname IN"
                    " ('quotes_frozen_after_send', 'quote_decisions_frozen')"
                )
            )
        ).all()
    assert (anonymized, trigger, frozen) == (1, "O", ["O", "O"])


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
