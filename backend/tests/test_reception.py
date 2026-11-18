"""Firmar la hoja de recepción por la API (F6 paso 2: RF-51, RF-52, RF-27).

Lo que garantiza la base de datos (la hoja firmada no cambia con ningún rol) está
en test_reception_db.py; aquí, el camino de la aplicación: firmar en pantalla o
en papel, lo que se congela, lo que no se acepta como firma, la corrección
después de firmar y la renuncia al presupuesto.
"""

import asyncio
import os
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm.exc import StaleDataError

from app.core.errors import ConflictError
from app.domain.reception import SignatureMethod
from app.infra.email import InMemoryEmailSender
from tests.conftest import Engines, TwoWorkshops
from tests.test_clients import open_workshop
from tests.test_concurrency import (
    GRACE,
    MakeAccount,
    dispose_global_engines,  # noqa: F401
    employee_with_access,
    finish,
    open_transaction,
)
from tests.test_employees import add_mechanic, invite_and_accept
from tests.test_work_orders import (
    URL,
    Shop,
    force_status,
    get,
    open_order,
    outbox,
    shop,
)
from tests.test_work_orders_db import seed_order

__all__ = ["outbox", "shop"]

# Una firma de verdad: dos trazos que se mueven, dentro de su lienzo.
STROKES = [[[10, 20], [40.04, 25], [80, 60]], [[100, 30], [120, 90]]]
SIGNATURE = {"width": 600, "height": 200, "strokes": STROKES}
RECEPTION = {
    "odometer_km": 123456,
    "reason": "Ruido al frenar",
    "dropped_off_by_name": "Jaime Sánchez",
    "dropped_off_by_phone": "688 777 666",
    "visible_damage": "Rayón en la puerta trasera",
    "belongings": "Silla infantil",
    "fuel_level": "quarter",
    "quote_waived": True,
}


def sheet_url(order_id: str) -> str:
    return f"{URL}/{order_id}/reception-sheet"


async def sign(
    client: AsyncClient, headers: dict[str, str], order: dict[str, Any], **body: Any
) -> Any:
    payload = {"version": order["version"], "method": "paper", **body}
    return await client.post(sheet_url(order["id"]), json=payload, headers=headers)


async def sign_on_screen(
    client: AsyncClient, headers: dict[str, str], order: dict[str, Any], **body: Any
) -> Any:
    return await sign(
        client,
        headers,
        order,
        method="screen",
        signer_name="Jaime Sánchez",
        signature=SIGNATURE,
        **body,
    )


async def stored_sheet(order_id: str) -> Any:
    engine = create_async_engine(os.environ["PLATFORM_DATABASE_URL"])
    try:
        async with engine.connect() as conn:
            return (
                await conn.execute(
                    text("SELECT * FROM reception_sheets WHERE work_order_id = :o"),
                    {"o": order_id},
                )
            ).one_or_none()
    finally:
        await engine.dispose()


async def audit_actions(client: AsyncClient, headers: dict[str, str]) -> list[Any]:
    response = await client.get("/api/v1/workshop/audit", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["entries"]


# --- Firmar --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_client_signs_on_screen_and_the_sheet_is_frozen(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"], **RECEPTION)
    assert order["reception_sheet"] is None
    assert order["can_sign_reception"] is True

    response = await sign_on_screen(client, shop.headers, order)
    assert response.status_code == 204, response.text

    after = await get(client, shop.headers, order["id"])
    sheet = after["reception_sheet"]
    assert {k: sheet[k] for k in sheet if k != "signed_at"} == {
        "signature_method": "screen",
        "recorded_by": "Ana López",
        "signer_name": "Jaime Sánchez",
        "quote_waived": True,
        "signature_purged": False,
    }
    assert after["can_sign_reception"] is False
    # Firmar cambia la versión de la orden: quien la tuviera abierta, recarga.
    assert after["version"] == order["version"] + 1

    stored = await stored_sheet(order["id"])
    # Los trazos, como números redondeados a la décima, en su lienzo.
    assert stored.signature == {
        "width": 600,
        "height": 200,
        "strokes": [[[10, 20], [40.0, 25], [80, 60]], [[100, 30], [120, 90]]],
    }
    # La copia congelada: los datos de recepción, sin nada personal.
    assert stored.snapshot["v"] == 1
    assert stored.snapshot["vehicle"]["plate"] == shop.car["plate"]
    assert {k: stored.snapshot[k] for k in ("odometer_km", "fuel_level", "reason")} == {
        "odometer_km": 123456,
        "fuel_level": "quarter",
        "reason": "Ruido al frenar",
    }
    assert "María" not in str(stored.snapshot)
    assert "Jaime" not in str(stored.snapshot)
    # Quién trajo el coche, en sus columnas, que se vacían al anonimizar.
    assert (stored.dropped_off_by_name, stored.dropped_off_by_phone) == (
        "Jaime Sánchez",
        "688 777 666",
    )

    [entry] = [
        e
        for e in await audit_actions(client, shop.headers)
        if e["action"] == "reception_signed"
    ]
    # Sin el nombre de quien firmó: la auditoría no se vacía al anonimizar.
    assert entry["details"] == {"signature_method": "screen"}


@pytest.mark.asyncio
async def test_the_admin_marks_it_signed_on_paper(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    assert (await sign(client, shop.headers, order)).status_code == 204
    sheet = (await get(client, shop.headers, order["id"]))["reception_sheet"]
    assert (sheet["signature_method"], sheet["signer_name"], sheet["quote_waived"]) == (
        "paper",
        None,
        False,
    )
    assert (await stored_sheet(order["id"])).signature is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "code"),
    [
        # En pantalla, sin trazos o sin quién firma, no hay firma.
        ({"method": "screen", "signer_name": "Jaime"}, "signature_required"),
        ({"method": "screen", "signature": SIGNATURE}, "signature_required"),
        ({"method": "screen", "signer_name": "  ", "signature": SIGNATURE}, None),
        # En papel, la firma está en el papel.
        ({"method": "paper", "signature": SIGNATURE}, "signature_not_expected"),
        # Un punto fuera del lienzo, o un lienzo imposible.
        (
            {
                "method": "screen",
                "signer_name": "Jaime",
                "signature": {**SIGNATURE, "strokes": [[[10, 20], [700, 60]]]},
            },
            "signature_invalid",
        ),
        (
            {
                "method": "screen",
                "signer_name": "Jaime",
                "signature": {**SIGNATURE, "width": 10},
            },
            "signature_invalid",
        ),
        # Un toque que no se mueve no es una firma.
        (
            {
                "method": "screen",
                "signer_name": "Jaime",
                "signature": {**SIGNATURE, "strokes": [[[10, 20], [10, 20]], [[5, 5]]]},
            },
            "signature_invalid",
        ),
        # Ni un punto de tres coordenadas, ni texto donde va un número.
        (
            {
                "method": "screen",
                "signer_name": "Jaime",
                "signature": {**SIGNATURE, "strokes": [[[10, 20, 30]]]},
            },
            None,
        ),
        (
            {
                "method": "screen",
                "signer_name": "Jaime",
                "signature": {"width": 600, "height": 200, "strokes": "<svg/>"},
            },
            None,
        ),
        ({"method": "pen"}, None),
    ],
)
async def test_what_is_not_a_signature_is_a_422(
    client: AsyncClient, shop: Shop, body: dict[str, Any], code: str | None
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    response = await sign(client, shop.headers, order, **body)
    assert response.status_code == 422, response.text
    if code:
        assert response.json()["code"] == code
    assert await stored_sheet(order["id"]) is None


@pytest.mark.asyncio
async def test_a_sheet_is_signed_once(client: AsyncClient, shop: Shop) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    assert (await sign(client, shop.headers, order)).status_code == 204
    again = await get(client, shop.headers, order["id"])
    response = await sign_on_screen(client, shop.headers, again)
    assert response.status_code == 409
    assert response.json()["code"] == "reception_already_signed"


@pytest.mark.asyncio
async def test_what_is_signed_is_the_version_that_was_shown(
    client: AsyncClient, shop: Shop
) -> None:
    """Si alguien corrige la recepción mientras el cliente lee la pantalla, su
    firma no vale para unos datos que no ha visto (409)."""
    order = await open_order(client, shop.headers, shop.car["id"], odometer_km=1000)
    edited = await client.patch(
        f"{URL}/{order['id']}",
        json={"version": order["version"], "odometer_km": 2000},
        headers=shop.headers,
    )
    assert edited.status_code == 204
    response = await sign_on_screen(client, shop.headers, order)
    assert response.status_code == 409
    assert response.json()["code"] == "modified_by_someone_else"
    assert await stored_sheet(order["id"]) is None


@pytest.mark.asyncio
async def test_a_closed_order_is_not_signed(client: AsyncClient, shop: Shop) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    await force_status(order["id"], "cancelled")
    closed = await get(client, shop.headers, order["id"])
    assert closed["can_sign_reception"] is False
    response = await sign(client, shop.headers, closed)
    assert response.status_code == 409
    assert response.json()["code"] == "work_order_closed"


@pytest.mark.asyncio
async def test_only_the_admin_signs(
    client: AsyncClient, shop: Shop, outbox: InMemoryEmailSender
) -> None:
    juan = await add_mechanic(client, shop.admin, "Juan")
    mechanic = await invite_and_accept(client, shop.admin, outbox, juan)
    order = await open_order(client, shop.headers, shop.car["id"])
    assert (await get(client, mechanic, order["id"]))["can_sign_reception"] is False
    assert (await sign(client, mechanic, order)).status_code == 403


@pytest.mark.asyncio
async def test_an_order_of_another_workshop_does_not_exist(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    other = (await open_workshop(client, "Taller B")).headers
    response = await sign(client, other, order)
    assert response.status_code == 404
    assert await stored_sheet(order["id"]) is None


# --- Corregir después de firmar (RF-52) ----------------------------------------------


@pytest.mark.asyncio
async def test_a_correction_after_signing_changes_the_order_and_not_the_sheet(
    client: AsyncClient, shop: Shop
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"], **RECEPTION)
    assert (await sign_on_screen(client, shop.headers, order)).status_code == 204
    signed = await get(client, shop.headers, order["id"])
    before = await stored_sheet(order["id"])

    response = await client.patch(
        f"{URL}/{order['id']}",
        json={
            "version": signed["version"],
            "odometer_km": 123465,
            "dropped_off_by_phone": "688 000 000",
            # Lo que no cambia no cuenta como corrección.
            "reason": "Ruido al frenar",
        },
        headers=shop.headers,
    )
    assert response.status_code == 204, response.text
    assert (await get(client, shop.headers, order["id"]))["odometer_km"] == 123465
    after = await stored_sheet(order["id"])
    assert after == before

    [entry] = [
        e
        for e in await audit_actions(client, shop.headers)
        if e["action"] == "reception_corrected"
    ]
    # Qué se corrigió, sin los valores: el teléfono es un dato personal.
    assert entry["details"] == {"fields": ["odometer_km", "dropped_off_by_phone"]}


@pytest.mark.asyncio
async def test_before_signing_or_for_the_responsible_nothing_is_recorded(
    client: AsyncClient, shop: Shop
) -> None:
    juan = await add_mechanic(client, shop.admin, "Juan")
    order = await open_order(client, shop.headers, shop.car["id"])
    edited = await client.patch(
        f"{URL}/{order['id']}",
        json={"version": order["version"], "odometer_km": 10},
        headers=shop.headers,
    )
    assert edited.status_code == 204
    current = await get(client, shop.headers, order["id"])
    assert (await sign(client, shop.headers, current)).status_code == 204
    signed = await get(client, shop.headers, order["id"])
    assigned = await client.patch(
        f"{URL}/{order['id']}",
        json={"version": signed["version"], "responsible_employee_id": juan},
        headers=shop.headers,
    )
    assert assigned.status_code == 204
    actions = [e["action"] for e in await audit_actions(client, shop.headers)]
    assert "reception_corrected" not in actions


# --- La renuncia al presupuesto (RF-27) ----------------------------------------------


async def mark_waiver(
    client: AsyncClient, headers: dict[str, str], order_id: str
) -> Any:
    current = await get(client, headers, order_id)
    return await client.post(
        f"{URL}/{order_id}/no-quote",
        json={"version": current["version"], "reason": "waiver"},
        headers=headers,
    )


@pytest.mark.asyncio
async def test_the_waiver_needs_the_sheet_signed_with_it(
    client: AsyncClient, shop: Shop
) -> None:
    # Con la casilla marcada en la orden, pero sin firmar: no.
    order = await open_order(client, shop.headers, shop.car["id"], quote_waived=True)
    refused = await mark_waiver(client, shop.headers, order["id"])
    assert refused.status_code == 409
    assert refused.json()["code"] == "waiver_requires_signed_reception"

    # Firmada sin la renuncia: tampoco.
    plain = await open_order(client, shop.headers, shop.car["id"])
    assert (await sign(client, shop.headers, plain)).status_code == 204
    refused = await mark_waiver(client, shop.headers, plain["id"])
    assert refused.status_code == 409

    # Firmada con ella: sí, aunque después se desmarque la casilla de la orden.
    assert (await sign(client, shop.headers, order)).status_code == 204
    signed = await get(client, shop.headers, order["id"])
    unticked = await client.patch(
        f"{URL}/{order['id']}",
        json={"version": signed["version"], "quote_waived": False},
        headers=shop.headers,
    )
    assert unticked.status_code == 204
    assert (await mark_waiver(client, shop.headers, order["id"])).status_code == 204
    assert (await get(client, shop.headers, order["id"]))["no_quote_reason"] == "waiver"


# --- A la vez ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_signatures_at_once_store_one(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """La segunda espera a la orden y la encuentra firmada: un 409, no el choque
    con el índice único (que sería un 500 sin `flush_or_conflict`)."""
    from app.services import reception as reception_service

    order = await seed_order(engines, two_workshops)
    a = order.workshop_id
    staff = await employee_with_access(engines, make_account, a, "admin")

    def sign_as(session: Any) -> Any:
        return reception_service.sign(
            session,
            a,
            staff.employee_id,
            staff.user_id,
            order.order_id,
            expected_version=1,
            method=SignatureMethod.PAPER,
            signer_name=None,
            signature=None,
        )

    async with open_transaction(a) as first, open_transaction(a) as second:
        await sign_as(first)
        work = asyncio.create_task(sign_as(second))
        await asyncio.sleep(GRACE)
        assert not work.done(), "la segunda firma debería esperar a la orden"
        await first.commit()
        outcome = await finish(second, work)

    # Ya firmada con otra versión: o la versión o la hoja la paran, nunca un 500.
    assert isinstance(outcome, ConflictError), outcome
    async with engines.platform.connect() as conn:
        count = await conn.scalar(
            text("SELECT count(*) FROM reception_sheets WHERE work_order_id = :o"),
            {"o": order.order_id},
        )
    assert count == 1


@pytest.mark.asyncio
async def test_a_correction_while_signing_waits_and_is_refused(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """Corregir la recepción mientras se firma: la corrección espera a la fila de
    la orden y, firmada ya con otra versión, se rechaza (el 409 de
    `modified_by_someone_else`). Nunca queda una corrección sin constancia."""
    from app.services import reception as reception_service
    from app.services import work_orders as order_service

    order = await seed_order(engines, two_workshops)
    a = order.workshop_id
    staff = await employee_with_access(engines, make_account, a, "admin")

    async with open_transaction(a) as first, open_transaction(a) as second:
        await reception_service.sign(
            first,
            a,
            staff.employee_id,
            staff.user_id,
            order.order_id,
            expected_version=1,
            method=SignatureMethod.PAPER,
            signer_name=None,
            signature=None,
        )
        work = asyncio.create_task(
            order_service.update_order(
                second,
                a,
                staff.user_id,
                order.order_id,
                expected_version=1,
                changes={"odometer_km": 5},
            )
        )
        await asyncio.sleep(GRACE)
        assert not work.done(), "la corrección debería esperar a la firma"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, StaleDataError), outcome
