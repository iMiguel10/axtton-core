"""Pruebas adversas del cierre de F6 que faltaban (los documentos generados).

- El trigger `reception_sheets_frozen` con los tres roles: el vaciado de lo
  personal no puede llevar de paso otro cambio, ni hacerse a medias, ni
  desbloquearse anonimizando a otro cliente; la hora de la firma la pone la base
  con cualquier rol; ningún rol de la aplicación vacía la tabla.
- Aislamiento: una hoja de A no se ve ni se vacía desde B, ni apunta a una orden
  o un empleado de B; las rutas nuevas del taller con ids de otro taller son el
  mismo 404 que un id que no existe; en el portal, quien compra el coche no ve
  los documentos del dueño anterior (RF-44, invariante 7).
- Carreras con dos transacciones reales (nunca `asyncio.gather` sobre la API):
  firmar mientras se corrige la recepción, se cancela o se entrega; entregar con
  km mientras se corrigen los de entrada, y al revés.
- Fugas: los documentos del portal sin nada interno; el informe de actuaciones
  sin `owners` no nombra a ningún cliente y sin `amounts` no lleva ningún importe,
  tampoco con cobros, decisiones con nota ni un titular anonimizado.
- RNF-40: hojas firmadas en pantalla y en papel por la API, y anonimizar.
- La firma: entradas hostiles dan 4xx, nunca un 500 ni una hoja guardada, y el
  SVG que sale de cualquier firma aceptada son solo números.
- La auditoría de firmar y de corregir no guarda datos personales.
"""

import asyncio
import json
import math
import re
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from hypothesis import example, given, settings
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core.errors import ConflictError
from app.domain.money import format_eur
from app.domain.reception import (
    InvalidSignature,
    SignatureMethod,
    clean_signature,
    signature_svg,
)
from app.services import reception as reception_service
from app.services import work_orders as order_service
from tests.conftest import Engines, TwoWorkshops
from tests.test_anonymize import (
    ANONYMIZE_SQL,
    DROPPED_OFF,
    PERSONAL,
    anonymize,
    dump_of_every_table,
)
from tests.test_anonymize import read as read_client
from tests.test_clients import create as create_client
from tests.test_clients import open_workshop
from tests.test_concurrency import (
    GRACE,
    MakeAccount,
    StaffMember,
    dispose_global_engines,  # noqa: F401 (autouse)
    employee_with_access,
    finish,
    open_transaction,
)
from tests.test_delivery_summary import deliver
from tests.test_delivery_summary import pdf as summary_pdf
from tests.test_employees import add_mechanic
from tests.test_payment import PAID, pay
from tests.test_portal_documents import sheet as portal_sheet
from tests.test_portal_documents import summary as portal_summary
from tests.test_portal_orders import Portal, order_ids, portal
from tests.test_portal_orders import read as portal_order
from tests.test_quote_decision import decide
from tests.test_quote_pdf import draft, text_of
from tests.test_quote_send import send
from tests.test_quotes import ORDERS
from tests.test_reception import (
    RECEPTION,
    SIGNATURE,
    sheet_url,
    sign,
    sign_on_screen,
    stored_sheet,
)
from tests.test_reception_db import ERASE, order, roles, run, sheet, signed
from tests.test_reception_pdf import pdf as reception_pdf
from tests.test_rls import set_workshops
from tests.test_vehicles import change_owner
from tests.test_vehicles import create as create_vehicle
from tests.test_vehicles import get as get_vehicle
from tests.test_work_orders import (
    URL,
    Shop,
    force_status,
    get,
    open_order,
    outbox,
    shop,
)
from tests.test_work_orders_db import Order, seed_order
from tests.test_worklog import add_work

__all__ = ["order", "outbox", "portal", "shop", "signed"]

ROLES = ["app", "platform", "owner"]
VEHICLES = "/api/v1/workshop/vehicles"
Call = Callable[[dict[str, str], str], Awaitable[Response]]


async def scalar(engines: Engines, sql: str, **params: Any) -> Any:
    async with engines.platform.connect() as conn:
        return await conn.scalar(text(sql), params)


async def client_of(engines: Engines, order_id: UUID) -> UUID:
    found = await scalar(
        engines, "SELECT client_id FROM work_orders WHERE id = :o", o=order_id
    )
    assert isinstance(found, UUID)
    return found


async def anonymize_by_sql(engines: Engines, client_id: UUID) -> None:
    async with engines.platform.begin() as conn:
        await conn.execute(
            text(
                "UPDATE clients SET name = '', phone = '',"
                " anonymized_at = clock_timestamp(), archived_at = clock_timestamp()"
                " WHERE id = :c"
            ),
            {"c": client_id},
        )


async def anonymize_maria(engines: Engines, order: Order) -> None:
    async with engines.platform.begin() as conn:
        await conn.execute(text(ANONYMIZE_SQL), {"w": order.workshop_id})


async def sheets_of(engines: Engines, order_id: UUID | str) -> int:
    count = await scalar(
        engines,
        "SELECT count(*) FROM reception_sheets WHERE work_order_id = :o",
        o=order_id,
    )
    assert isinstance(count, int)
    return count


async def other_employee(engines: Engines, workshop_id: UUID) -> UUID:
    async with engines.platform.begin() as conn:
        found = await conn.scalar(
            text(
                "INSERT INTO employees (workshop_id, name, role)"
                " VALUES (:w, 'Otra administradora', 'admin') RETURNING id"
            ),
            {"w": workshop_id},
        )
    assert isinstance(found, UUID)
    return found


# --- El trigger con los tres roles ------------------------------------------------

ERASE_SET = (
    "dropped_off_by_name = NULL, dropped_off_by_phone = NULL, signer_name = NULL"
)
# Lo que se intenta colar junto al vaciado permitido, con el cliente ya
# anonimizado: el trigger solo admite el vaciado, y nada más en la misma fila.
SMUGGLED = {
    "the frozen copy": "snapshot = snapshot || '{\"odometer_km\": 1}'",
    "the strokes": (
        'signature = \'{"width": 600, "height": 200, "strokes": [[[1, 1], [2, 2]]]}\''
    ),
    # El borrado de la firma llega con su plazo (RF-56, F8), no al anonimizar.
    "an early purge": "signature = NULL, signature_purged_at = clock_timestamp()",
    "the time of signing": "signed_at = signed_at + interval '1 second'",
    "the waiver": "quote_waived = NOT quote_waived",
    "the method": "signature_method = 'paper', signature = NULL",
    "who recorded it": "recorded_by_employee_id = :other",
    "the order": "work_order_id = gen_random_uuid()",
    "the id": "id = gen_random_uuid()",
    "the creation": "created_at = created_at - interval '1 day'",
    "the workshop": "workshop_id = gen_random_uuid()",
}
# A medias, o cambiando lo personal por otra cosa: tampoco.
PARTIAL = {
    "only the signer": "signer_name = NULL",
    "only who brought it": "dropped_off_by_name = NULL, dropped_off_by_phone = NULL",
    "all but the name": "dropped_off_by_phone = NULL, signer_name = NULL",
    "another name instead": (
        "dropped_off_by_name = 'Otro', dropped_off_by_phone = NULL, signer_name = NULL"
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("change", list(SMUGGLED.values()), ids=list(SMUGGLED))
async def test_erasing_the_personal_data_carries_no_other_change_with_any_role(
    engines: Engines, two_workshops: TwoWorkshops, signed: Order, role: str, change: str
) -> None:
    """A la aplicación la para el permiso por columna; a la plataforma y al
    dueño, el trigger. La fila queda exactamente como estaba."""
    other = await other_employee(engines, signed.workshop_id)
    await anonymize_maria(engines, signed)
    before = await sheet(engines, signed)
    with pytest.raises(
        DBAPIError, match="cannot change|permission denied|row-level security"
    ):
        await run(
            roles(engines)[role],
            signed,
            f"UPDATE reception_sheets SET {ERASE_SET}, {change}"
            " WHERE work_order_id = :o",
            other=other,
        )
    assert await sheet(engines, signed) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("change", list(PARTIAL.values()), ids=list(PARTIAL))
async def test_the_personal_data_is_erased_whole_or_not_at_all_with_any_role(
    engines: Engines, signed: Order, role: str, change: str
) -> None:
    await anonymize_maria(engines, signed)
    before = await sheet(engines, signed)
    with pytest.raises(DBAPIError, match="cannot change"):
        await run(
            roles(engines)[role],
            signed,
            f"UPDATE reception_sheets SET {change} WHERE work_order_id = :o",
        )
    assert await sheet(engines, signed) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_anonymizing_another_client_does_not_unlock_this_sheet(
    engines: Engines, signed: Order, role: str
) -> None:
    """El trigger mira al cliente de la orden de esa hoja, no a cualquier
    cliente anonimizado del taller que tenga alguna orden."""
    pedros_order = await order_in(engines, signed.workshop_id, number=2)
    await anonymize_by_sql(engines, await client_of(engines, pedros_order))
    before = await sheet(engines, signed)
    with pytest.raises(DBAPIError, match="cannot change"):
        await run(roles(engines)[role], signed, ERASE)
    assert await sheet(engines, signed) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_the_time_of_signing_is_the_servers_with_any_role(
    engines: Engines, two_workshops: TwoWorkshops, order: Order, role: str
) -> None:
    """test_reception_db.py lo prueba con la aplicación; la plataforma y el
    dueño tampoco pueden fecharla."""
    await run(
        roles(engines)[role],
        order,
        "INSERT INTO reception_sheets (workshop_id, work_order_id, signature_method,"
        " recorded_by_employee_id, snapshot, quote_waived, signed_at)"
        " VALUES (:w, :o, 'paper', :e, '{}', false, '2001-01-01')",
        e=two_workshops.admin_a,
    )
    assert (await sheet(engines, order)).signed_at.year > 2001


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform"])
async def test_no_application_role_empties_the_signed_sheets(
    engines: Engines, signed: Order, role: str
) -> None:
    """TRUNCATE no pasa por los triggers de fila: solo el dueño lo tiene (para
    `reset_data`), nunca la aplicación ni la plataforma."""
    with pytest.raises(DBAPIError, match="permission denied"):
        await run(roles(engines)[role], signed, "TRUNCATE reception_sheets")
    assert await sheets_of(engines, signed.order_id) == 1


@pytest.mark.asyncio
async def test_erasing_cannot_rewrite_the_numbers_of_the_frozen_copy(
    engines: Engines, signed: Order
) -> None:
    await anonymize_maria(engines, signed)
    before = await sheet(engines, signed)
    try:
        with pytest.raises(DBAPIError, match="cannot change"):
            await run(
                engines.platform,
                signed,
                f"UPDATE reception_sheets SET {ERASE_SET},"
                " snapshot = jsonb_set(snapshot, '{odometer_km}', '123456.0')"
                " WHERE work_order_id = :o",
            )
    finally:
        after = await sheet(engines, signed)
        # Lo que se ve: el valor guardado ya no es el que se firmó.
        assert json.dumps(after.snapshot) == json.dumps(before.snapshot)


# --- Aislamiento entre talleres en la base de datos --------------------------------


async def order_in(engines: Engines, workshop_id: UUID, number: int = 1) -> UUID:
    """Una orden recibida de otra clienta (de otro taller, o del mismo con otro
    número), escrita como `seed_order`."""
    async with engines.platform.begin() as conn:
        client = await conn.scalar(
            text(
                "INSERT INTO clients (workshop_id, name, phone)"
                " VALUES (:w, 'Marta', '622') RETURNING id"
            ),
            {"w": workshop_id},
        )
        vehicle = await conn.scalar(
            text(
                "INSERT INTO vehicles (workshop_id, plate, plate_normalized)"
                " VALUES (:w, '2', '2') RETURNING id"
            ),
            {"w": workshop_id},
        )
        order_id = await conn.scalar(
            text(
                "INSERT INTO work_orders"
                " (workshop_id, year, number, type, vehicle_id, client_id, status)"
                " VALUES (:w, 2026, :n, 'breakdown', :v, :c, 'received') RETURNING id"
            ),
            {"w": workshop_id, "v": vehicle, "c": client, "n": number},
        )
        await conn.execute(
            text(
                "INSERT INTO work_order_status_changes"
                " (workshop_id, work_order_id, to_status, cause)"
                " VALUES (:w, :o, 'received', 'opened')"
            ),
            {"w": workshop_id, "o": order_id},
        )
    assert isinstance(order_id, UUID)
    return order_id


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "owner"])
async def test_from_another_workshop_a_signed_sheet_is_neither_seen_nor_erased(
    engines: Engines, two_workshops: TwoWorkshops, signed: Order, role: str
) -> None:
    """Con el cliente de A ya anonimizado (el vaciado sería legítimo en A), desde
    B la hoja no existe: no se lee y el UPDATE no toca ninguna fila."""
    await anonymize_maria(engines, signed)
    before = await sheet(engines, signed)
    async with roles(engines)[role].begin() as conn:
        await set_workshops(conn, two_workshops.b)
        seen = await conn.scalar(text("SELECT count(*) FROM reception_sheets"))
        erased = await conn.execute(text(ERASE), {"o": signed.order_id})
    assert (seen, erased.rowcount) == (0, 0)
    assert await sheet(engines, signed) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform"])
async def test_a_sheet_cannot_join_an_order_or_an_employee_of_another_workshop(
    engines: Engines, two_workshops: TwoWorkshops, order: Order, role: str
) -> None:
    """Las FK compuestas: la plataforma se salta RLS, así que son lo único que
    la para; la aplicación, con A fijado, tampoco lo consigue."""
    order_b = await order_in(engines, two_workshops.b)
    insert = (
        "INSERT INTO reception_sheets (workshop_id, work_order_id, signature_method,"
        " recorded_by_employee_id, snapshot, quote_waived)"
        " VALUES (:w, :target, 'paper', :e, '{}', false)"
    )
    for target, employee in (
        (order_b, two_workshops.admin_a),
        (order.order_id, two_workshops.admin_b),
    ):
        with pytest.raises(DBAPIError, match="foreign key"):
            await run(roles(engines)[role], order, insert, target=target, e=employee)
    assert await sheets_of(engines, order.order_id) == 0
    assert await sheets_of(engines, order_b) == 0


# --- Aislamiento de las rutas ------------------------------------------------------


async def delivered_signed_order(client: AsyncClient, shop: Shop) -> str:
    """Una orden con la recepción completa, firmada en pantalla y entregada con
    sus km."""
    order = await open_order(client, shop.headers, shop.car["id"], **RECEPTION)
    signed_now = await sign_on_screen(client, shop.headers, order)
    assert signed_now.status_code == 204, signed_now.text
    await force_status(order["id"], "ready")
    delivered = await deliver(client, shop, order["id"], odometer_km=130_000)
    assert delivered.status_code == 204, delivered.text
    order_id: str = order["id"]
    return order_id


@pytest.mark.asyncio
async def test_f6_workshop_routes_with_ids_of_another_workshop_answer_like_missing_ones(
    client: AsyncClient, shop: Shop
) -> None:
    """Desde A, con lo de B (una orden sin firmar, otra firmada y entregada, su
    coche): el mismo 404 que con un id que no existe, y en B nada cambia. Al
    final, B lo pide todo y le sale: el 404 era el aislamiento."""
    admin_b = await open_workshop(client, "Taller B")
    marta = await create_client(client, admin_b.headers, name="Marta")
    car_b = await create_vehicle(
        client, admin_b.headers, marta["id"], plate="5678 XYZ", make="Opel"
    )
    b = Shop(admin_b, marta, marta, car_b)
    delivered_b = await delivered_signed_order(client, b)
    open_b = await open_order(client, b.headers, car_b["id"])

    def signing(method: str) -> Call:
        async def call(headers: dict[str, str], order_id: str) -> Response:
            body: dict[str, Any] = {"version": open_b["version"], "method": method}
            if method == "screen":
                body |= {"signer_name": "Intruso", "signature": SIGNATURE}
            return await client.post(sheet_url(order_id), json=body, headers=headers)

        return call

    async def sheet_pdf(headers: dict[str, str], order_id: str) -> Response:
        return await reception_pdf(client, headers, order_id)

    async def summary(headers: dict[str, str], order_id: str) -> Response:
        return await summary_pdf(client, headers, order_id)

    def report(**params: Any) -> Call:
        async def call(headers: dict[str, str], vehicle_id: str) -> Response:
            return await client.get(
                f"{VEHICLES}/{vehicle_id}/report/pdf", params=params, headers=headers
            )

        return call

    attacks: list[tuple[str, Call, str]] = [
        ("firmar en papel", signing("paper"), open_b["id"]),
        ("firmar en pantalla", signing("screen"), open_b["id"]),
        ("PDF de la hoja", sheet_pdf, delivered_b),
        ("resumen de entrega", summary, delivered_b),
        ("informe", report(), car_b["id"]),
        ("informe con titulares", report(owners=True), car_b["id"]),
        ("informe con importes", report(owners=True, amounts=True), car_b["id"]),
    ]
    for name, call, theirs in attacks:
        response = await call(shop.headers, theirs)
        missing = await call(shop.headers, str(uuid4()))
        assert response.status_code == 404, (name, response.text)
        assert response.json() == missing.json(), name

    assert await stored_sheet(open_b["id"]) is None
    assert (await get(client, b.headers, open_b["id"]))["version"] == open_b["version"]

    for name, call, theirs in attacks[2:]:
        assert (await call(b.headers, theirs)).status_code == 200, name
    assert (await signing("paper")(b.headers, open_b["id"])).status_code == 204


@pytest.mark.asyncio
async def test_rf44_the_new_owner_of_the_car_gets_none_of_the_previous_documents(
    client: AsyncClient, portal: Portal
) -> None:
    """El coche de María, firmado y entregado, se vende a Luis, que lo trae otra
    vez. Luis no descarga nada de la orden de María; María sigue descargando lo
    suyo (el acceso va por la orden, invariante 7) y no lo de Luis."""
    shop = portal.shop
    old = await delivered_signed_order(client, shop)
    car = await get_vehicle(client, shop.headers, shop.car["id"])
    moved = await change_owner(client, shop.headers, car, shop.luis["id"])
    assert moved.status_code == 204, moved.text
    new = await open_order(client, shop.headers, shop.car["id"])
    assert (await sign(client, shop.headers, new)).status_code == 204

    assert await order_ids(client, portal.luis) == {new["id"]}
    for download in (portal_sheet, portal_summary):
        refused = await download(client, portal.luis, old)
        assert refused.status_code == 404, download.__name__
        assert refused.json()["code"] == "work_order_not_found"
    assert (await portal_order(client, portal.luis, old)).status_code == 404

    assert (await portal_sheet(client, portal.maria, old)).status_code == 200
    assert (await portal_summary(client, portal.maria, old)).status_code == 200
    theirs = await portal_sheet(client, portal.maria, new["id"])
    assert theirs.status_code == 404
    assert theirs.json()["code"] == "work_order_not_found"


# --- Fugas: los documentos del portal -------------------------------------------

INTERNAL_NOTE = "NOTA-INTERNA el cliente regatea siempre"
DECISION_NOTE = "NOTA-DE-LA-DECISION lo dijo de mala gana"
# Las horas, como número suelto: no dentro de una fecha ("…:57.254").
HOURS = re.compile(r"(?<![\d.,:])7[.,]25(?!\d)")


async def staff_names(engines: Engines, shop: Shop) -> list[str]:
    async with engines.platform.connect() as conn:
        names = (
            await conn.scalars(
                text("SELECT name FROM employees WHERE workshop_id = :w"),
                {"w": shop.admin.headers["X-Workshop-Id"]},
            )
        ).all()
    return list(names)


async def to_diagnosing(client: AsyncClient, shop: Shop, order: dict[str, Any]) -> None:
    moved = await client.post(
        f"{ORDERS}/{order['id']}/status",
        json={"version": order["version"], "to_status": "diagnosing"},
        headers=shop.headers,
    )
    assert moved.status_code == 204, moved.text


async def full_history(
    client: AsyncClient,
    shop: Shop,
    mechanic: str,
    *,
    decision_note: str,
    km_out: int,
) -> tuple[str, str]:
    """Una orden con todo lo interno que puede tener: la recepción completa con
    quién trajo el coche, una nota interna, un trabajo de un mecánico con sus
    horas, el presupuesto aprobado por teléfono con nota, la hoja firmada en
    pantalla y la entrega con sus km. Devuelve la orden y su versión aprobada."""
    order = await open_order(client, shop.headers, shop.car["id"], **RECEPTION)
    await to_diagnosing(client, shop, order)
    note = await client.post(
        f"{ORDERS}/{order['id']}/notes",
        json={"body": INTERNAL_NOTE},
        headers=shop.headers,
    )
    assert note.status_code == 201, note.text
    work = await add_work(client, shop.headers, order["id"], mechanic, hours="7.25")
    assert work.status_code == 201, work.text
    quote_id = await draft(client, shop, order["id"])
    assert (await send(client, shop, order["id"], quote_id)).status_code == 204
    decided = await decide(client, shop, order["id"], quote_id, note=decision_note)
    assert decided.status_code == 204, decided.text
    current = await get(client, shop.headers, order["id"])
    assert (await sign_on_screen(client, shop.headers, current)).status_code == 204
    await force_status(order["id"], "ready")
    delivered = await deliver(client, shop, order["id"], odometer_km=km_out)
    assert delivered.status_code == 204, delivered.text
    order_id: str = order["id"]
    return order_id, quote_id


@pytest.mark.asyncio
async def test_rf43_the_portal_documents_carry_nothing_internal(
    client: AsyncClient, portal: Portal, engines: Engines
) -> None:
    """La orden, su hoja firmada y su resumen de entrega, tal como los lee el
    cliente, juntos y en texto: ni quién recogió la firma ni quién hizo cada
    trabajo, ni la nota interna, ni la nota de la decisión, ni las horas."""
    shop = portal.shop
    mechanic = await add_mechanic(client, shop.admin, "Juanísimo Escondido")
    order_id, _ = await full_history(
        client, shop, mechanic, decision_note=DECISION_NOTE, km_out=187_500
    )

    detail = await portal_order(client, portal.maria, order_id)
    assert detail.status_code == 200, detail.text
    seen = "\n".join(
        [
            detail.text,
            text_of(await portal_sheet(client, portal.maria, order_id)),
            text_of(await portal_summary(client, portal.maria, order_id)),
        ]
    ).lower()

    # Lo que sí debe estar: sin esto, la búsqueda podría no mirar nada.
    for expected in ("cambio de pastillas delanteras", "jaime sánchez", "187.500 km"):
        assert expected in seen, expected
    staff = await staff_names(engines, shop)
    assert len(staff) >= 2  # la administradora y el mecánico
    for secret in (
        *staff,
        INTERNAL_NOTE,
        DECISION_NOTE,
        "recogida en el taller por",
        "registrada por",
        "hourly_cost",
        "recorded_by",
    ):
        assert secret.lower() not in seen, secret
    assert not HOURS.search(seen), "las horas del trabajo"


# --- Fugas: el informe de actuaciones ----------------------------------------------


@pytest.mark.asyncio
async def test_the_report_names_no_client_without_owners_and_no_amount_without_amounts(
    client: AsyncClient, shop: Shop, engines: Engines
) -> None:
    """El coche de María (orden con todo, cobrada) pasa a Luis (orden aprobada,
    abierta) y María se anonimiza. Con cualquier combinación de `owners` y
    `amounts`, lo que no se pidió no aparece por ningún camino: ni los nombres
    (tampoco "Cliente eliminado", ni quién trajo el coche, ni el nombre escrito en
    la nota de una decisión), ni el importe aprobado, ni lo cobrado."""
    mechanic = await add_mechanic(client, shop.admin, "Juanísimo Escondido")
    maria_order, _ = await full_history(
        client,
        shop,
        mechanic,
        decision_note="Lo aprobó María por teléfono",
        km_out=130_000,
    )
    paid = await pay(
        client, shop.headers, await get(client, shop.headers, maria_order), **PAID
    )
    assert paid.status_code == 204, paid.text

    car = await get_vehicle(client, shop.headers, shop.car["id"])
    moved = await change_owner(client, shop.headers, car, shop.luis["id"])
    assert moved.status_code == 204, moved.text
    luis_order = await open_order(
        client, shop.headers, shop.car["id"], odometer_km=140_000
    )
    await to_diagnosing(client, shop, luis_order)
    luis_quote = await draft(client, shop, luis_order["id"])
    assert (await send(client, shop, luis_order["id"], luis_quote)).status_code == 204
    decided = await decide(
        client, shop, luis_order["id"], luis_quote, note="Luis dice que sí"
    )
    assert decided.status_code == 204, decided.text

    maria = await read_client(client, shop.headers, shop.maria["id"])
    assert (await anonymize(client, shop.headers, maria)).status_code == 204

    async with engines.platform.connect() as conn:
        totals = (
            await conn.scalars(
                text("SELECT total_cents FROM quotes WHERE status = 'approved'")
            )
        ).all()
    assert len(totals) == 2
    paid_cents = PAID["amount_cents"]
    assert isinstance(paid_cents, int)
    amounts = [format_eur(total).removesuffix(" €") for total in totals]
    amounts.append(format_eur(paid_cents).removesuffix(" €"))
    names = (
        "maría",
        "luis",
        "cliente eliminado",
        "cliente:",
        "jaime",
        "sánchez",
        *(name.lower() for name in await staff_names(engines, shop)),
    )

    async def report(**params: Any) -> str:
        response = await client.get(
            f"{VEHICLES}/{shop.car['id']}/report/pdf",
            params=params,
            headers=shop.headers,
        )
        return text_of(response).lower()

    basic = await report()
    with_amounts = await report(amounts=True)
    with_owners = await report(owners=True)

    # Lo que sí debe estar en cada uno: las dos órdenes, y lo que se pidió.
    for content in (basic, with_amounts, with_owners):
        assert "2 órdenes" in content
        assert "cambio de pastillas delanteras" in content
    assert "importe del presupuesto aceptado" in with_amounts
    assert "cliente: luis" in with_owners
    assert "cliente: cliente eliminado" in with_owners

    for content, label in ((basic, "básico"), (with_amounts, "con importes")):
        for name in names:
            assert name not in content, (label, name)
    for content, label in ((basic, "básico"), (with_owners, "con titulares")):
        assert "€" not in content, label
        for amount in amounts:
            assert amount not in content, (label, amount)
    for content in (basic, with_amounts, with_owners):
        assert INTERNAL_NOTE.lower() not in content
        assert "lo aprobó" not in content
        assert "dice que sí" not in content
    # Lo cobrado no sale ni con importes: el informe da el presupuesto aceptado.
    assert format_eur(paid_cents).lower() not in with_amounts


# --- RNF-40: hojas firmadas por la API y anonimizar -------------------------------

PAPER_PERSON = {
    "dropped_off_by_name": "Rosa Trajo Coche",
    "dropped_off_by_phone": "677 555 444",
}
PAPER_SIGNER = "Rosa Firmante Papel"


@pytest.mark.asyncio
async def test_rnf40_sheets_signed_on_screen_and_on_paper_leave_nothing_after_anonymizing(
    client: AsyncClient, shop: Shop
) -> None:
    """Las dos hojas por el camino de verdad (la de test_anonymize.py se escribe
    con SQL y con la copia vacía): tras anonimizar, ni María, ni quien trajo el
    coche, ni quien firmó quedan en ninguna tabla ni en el PDF de ninguna hoja,
    que dice "Cliente eliminado". La firma se queda hasta su plazo (RF-56)."""
    updated = await client.patch(
        f"/api/v1/workshop/clients/{shop.maria['id']}",
        json={"version": shop.maria["version"], **PERSONAL},
        headers=shop.headers,
    )
    assert updated.status_code == 204, updated.text

    on_screen = await open_order(
        client, shop.headers, shop.car["id"], **{**RECEPTION, **DROPPED_OFF}
    )
    assert (await sign_on_screen(client, shop.headers, on_screen)).status_code == 204
    await force_status(on_screen["id"], "ready")
    assert (await deliver(client, shop, on_screen["id"])).status_code == 204
    on_paper = await open_order(client, shop.headers, shop.car["id"], **PAPER_PERSON)
    # En papel no se guarda quién firmó (cierre de F6): la API lo rechaza.
    named = await sign(client, shop.headers, on_paper, signer_name=PAPER_SIGNER)
    assert named.status_code == 422
    assert named.json()["code"] == "signer_name_not_expected"
    paper = await sign(client, shop.headers, on_paper)
    assert paper.status_code == 204, paper.text
    await force_status(on_paper["id"], "ready")
    assert (await deliver(client, shop, on_paper["id"])).status_code == 204

    # Antes de anonimizar, el PDF los lleva: lo de después no pasa por azar.
    before = text_of(await reception_pdf(client, shop.headers, on_screen["id"]))
    assert PERSONAL["name"] in before and DROPPED_OFF["dropped_off_by_name"] in before
    before = text_of(await reception_pdf(client, shop.headers, on_paper["id"]))
    assert PAPER_PERSON["dropped_off_by_name"] in before
    assert (await stored_sheet(on_paper["id"])).signer_name is None

    maria = await read_client(client, shop.headers, shop.maria["id"])
    assert (await anonymize(client, shop.headers, maria)).status_code == 204

    searched = [
        *PERSONAL.values(),
        *DROPPED_OFF.values(),
        *PAPER_PERSON.values(),
        PAPER_SIGNER,
        "maria sanchez",
        "699123987",
        "677555444",
        "688777666",
    ]
    dump = await dump_of_every_table()
    assert [value for value in searched if value.lower() in dump] == []

    for done in (on_screen, on_paper):
        content = text_of(await reception_pdf(client, shop.headers, done["id"]))
        assert "Cliente eliminado" in content
        assert [v for v in searched if v.lower() in content.lower()] == []
    assert (await stored_sheet(on_screen["id"])).signature is not None


# --- La firma: entradas hostiles ---------------------------------------------------

STROKES_JSON = "[[[10, 20], [30, 40]]]"


def signature_body(version: int, signature: str, signer: str = '"Jaime"') -> str:
    return (
        f'{{"version": {version}, "method": "screen", "signer_name": {signer},'
        f' "signature": {signature}}}'
    )


def frame(width: str = "600", height: str = "200", strokes: str = STROKES_JSON) -> str:
    return f'{{"width": {width}, "height": {height}, "strokes": {strokes}}}'


def with_point(point: str) -> str:
    return frame(strokes=f"[[{point}, [30, 40]]]")


BIG_INT = "1" + "0" * 400  # mayor que el mayor float
HUGE_INT = "1" + "0" * 5000  # más cifras de las que Python convierte
# NaN e Infinity no son JSON, pero el analizador de Python los acepta (y 1e999
# llega como infinito). Pydantic los rechaza, pero el 422 de FastAPI repite la
# entrada en su cuerpo, y Starlette no sabe escribir NaN en JSON: un 500.
NON_FINITE: dict[str, str] = {
    "width NaN": frame(width="NaN"),
    "width Infinity": frame(width="Infinity"),
    "height -Infinity": frame(height="-Infinity"),
    "width 1e999": frame(width="1e999"),
    "punto NaN": with_point("[NaN, 20]"),
    "punto Infinity": with_point("[Infinity, 20]"),
    "punto -1e999": with_point("[10, -1e999]"),
}


HOSTILE_SIGNATURES: dict[str, str] = {
    "width enorme entero": frame(width=BIG_INT),
    "width con 5000 cifras": frame(width=HUGE_INT),
    "width 1e308": frame(width="1e308"),
    "width true": frame(width="true"),
    "width texto": frame(width='"600px"'),
    "width null": frame(width="null"),
    "width negativo": frame(width="-600"),
    "punto 1e308": with_point("[1e308, 20]"),
    "punto enorme entero": with_point(f"[{BIG_INT}, 20]"),
    "punto apenas negativo": with_point("[-0.0001, 20]"),
    "punto objeto": with_point('{"x": 1, "y": 2}'),
    "punto texto": with_point('"10,20"'),
    "punto con null": with_point("[null, 20]"),
    "punto con letras": with_point('["x", 20]'),
    "punto anidado": with_point("[[1, 2], 3]"),
    "punto de una coordenada": with_point("[1]"),
    "punto de tres coordenadas": with_point("[1, 2, 3]"),
    "61 trazos": frame(strokes="[" + ", ".join(["[[1, 2], [3, 4]]"] * 61) + "]"),
    "trazo de 2001 puntos": frame(strokes="[[" + ", ".join(["[1, 2]"] * 2001) + "]]"),
    "6060 puntos en total": frame(
        strokes="["
        + ", ".join(
            ["[" + ", ".join(["[1, 2]", "[3, 4]"] * 50 + ["[5, 6]"]) + "]"] * 60
        )
        + "]"
    ),
    "trazos como objeto": frame(strokes="{}"),
    "trazos como SVG": frame(strokes='"<svg onload=alert(1)/>"'),
    "trazos muy anidados": frame(strokes="[" * 100_000 + "]" * 100_000),
    "firma como SVG": '"<svg xmlns=\\"http://www.w3.org/2000/svg\\"><script/></svg>"',
    "firma como lista": "[]",
}


@pytest.mark.asyncio
async def test_a_hostile_signature_is_a_client_error_never_a_500_nor_stored(
    client: AsyncClient, shop: Shop
) -> None:
    """Cada entrada, por la API con el cuerpo tal cual: 400 o 422, y la orden
    sigue sin firmar. Al final se firma de verdad: la orden podía firmarse."""
    order = await open_order(client, shop.headers, shop.car["id"])
    version = order["version"]
    bodies = {
        name: signature_body(version, signature)
        for name, signature in HOSTILE_SIGNATURES.items()
    }
    bodies |= {
        "nombre de 201 letras": signature_body(version, frame(), '"' + "a" * 201 + '"'),
        "nombre como objeto": signature_body(version, frame(), '{"a": 1}'),
        "no es JSON": "{version: 1, method: screen",
    }
    headers = {**shop.headers, "content-type": "application/json"}
    for name, body in bodies.items():
        response = await client.post(
            sheet_url(order["id"]), content=body.encode(), headers=headers
        )
        assert response.status_code in (400, 422), (name, response.status_code)
    assert await stored_sheet(order["id"]) is None

    # Los bordes del lienzo sí valen.
    edges = frame(strokes="[[[0, 0], [600, 200]], [[0, 200], [-0.0, 0]]]")
    response = await client.post(
        sheet_url(order["id"]),
        content=signature_body(version, edges).encode(),
        headers=headers,
    )
    assert response.status_code == 204, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("signature", list(NON_FINITE.values()), ids=list(NON_FINITE))
async def test_a_non_finite_number_in_a_signature_is_a_422_not_a_500(
    client: AsyncClient, shop: Shop, signature: str
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"])
    response = await client.post(
        sheet_url(order["id"]),
        content=signature_body(order["version"], signature).encode(),
        headers={**shop.headers, "content-type": "application/json"},
    )
    assert response.status_code == 422, response.text
    # El 422 no devuelve lo que se mandó (`input`), que era lo que lo rompía.
    assert all("input" not in error for error in response.json()["detail"])
    assert await stored_sheet(order["id"]) is None


NUMBER = r"-?\d+(?:\.\d)?"
PATH = rf'<path d="M{NUMBER} {NUMBER}(?: L{NUMBER} {NUMBER})+"/>'
SVG_SHAPE = re.compile(
    '<svg xmlns="http://www.w3.org/2000/svg"'
    rf' viewBox="0 0 {NUMBER} {NUMBER}">'
    '<g fill="none" stroke="#111" stroke-width="2.5"'
    ' stroke-linecap="round" stroke-linejoin="round">'
    rf"(?:{PATH})+</g></svg>"
)
# Casi siempre números dentro del lienzo, para que muchas firmas se acepten y su
# SVG se mire; a veces, los que pueden romperlo.
EDGE_NUMBERS = [math.nan, math.inf, -math.inf, -0.0, 1e308, -1e-300, 10**400, -1]
coordinates = st.one_of(
    st.floats(min_value=0, max_value=50),
    st.integers(min_value=0, max_value=50),
    st.sampled_from(EDGE_NUMBERS),
    st.floats(allow_nan=True, allow_infinity=True),
)
frames = st.one_of(
    st.floats(min_value=50, max_value=4000),
    st.sampled_from([50, 4000, 49.99, 4000.01, *EDGE_NUMBERS]),
)
points = st.one_of(
    st.lists(coordinates, min_size=2, max_size=2),
    st.lists(coordinates, min_size=0, max_size=3),
)
strokes_of = st.lists(st.lists(points, min_size=1, max_size=6), max_size=5)


@given(frames, frames, strokes_of)
# Los que tienen que salir siempre, no solo cuando el azar los encuentre.
@example(600, 200, [[[math.nan, 1], [2, 3]]])
@example(600, 200, [[[1, math.inf], [2, 3]]])
@example(600, 200, [[[1, 2], [-math.inf, 3]]])
@example(math.nan, 200, [[[1, 2], [2, 3]]])
@example(600, math.inf, [[[1, 2], [2, 3]]])
@example(600, 200, [[[10**400, 2], [2, 3]]])
@example(600, 200, [[[-0.0, 2], [2, -0.0]]])
@settings(max_examples=500, deadline=None)
def test_any_numbers_are_refused_or_drawn_only_as_numbers(
    width: float, height: float, strokes: list[list[list[float]]]
) -> None:
    """Con cualquier número (NaN, infinitos, enteros más grandes que un float):
    o `InvalidSignature`, o una firma que se guarda como JSON estricto y cuyo SVG
    es solo trazos de números. Nunca otra excepción, que sería un 500."""
    try:
        cleaned = clean_signature(width, height, strokes)
    except InvalidSignature:
        return
    json.dumps(cleaned, allow_nan=False)
    assert SVG_SHAPE.fullmatch(signature_svg(cleaned)), signature_svg(cleaned)


# --- La auditoría de firmar y de corregir ------------------------------------------

SCREEN_SIGNER = "Lucía Firmante Secreta"
CORRECTION = {
    "dropped_off_by_name": "Pedro Corregido Secreto",
    "dropped_off_by_phone": "655 444 333",
    "visible_damage": "Golpe secreto en el capó",
    "belongings": "Maletín secreto",
}


@pytest.mark.asyncio
async def test_the_audit_of_signing_and_correcting_keeps_no_personal_data(
    client: AsyncClient, shop: Shop, engines: Engines
) -> None:
    """El registro de auditoría no se vacía al anonimizar: firmar y corregir la
    recepción dejan constancia de qué pasó, nunca de lo que se escribió. Se
    busca en todas sus filas, no solo en los `details` de la acción."""
    order = await open_order(client, shop.headers, shop.car["id"], **RECEPTION)
    signed_now = await sign(
        client,
        shop.headers,
        order,
        method="screen",
        signer_name=SCREEN_SIGNER,
        signature=SIGNATURE,
    )
    assert signed_now.status_code == 204, signed_now.text
    current = await get(client, shop.headers, order["id"])
    corrected = await client.patch(
        f"{URL}/{order['id']}",
        json={"version": current["version"], **CORRECTION},
        headers=shop.headers,
    )
    assert corrected.status_code == 204, corrected.text

    async with engines.platform.connect() as conn:
        audit = "\n".join(
            (await conn.scalars(text("SELECT a::text FROM audit_log a"))).all()
        ).lower()
    assert "reception_signed" in audit and "reception_corrected" in audit
    # Quién trajo el coche y quién firmó, y el texto libre de la recepción, que
    # puede llevar datos personales ("la silla de Lucía").
    personal = [
        SCREEN_SIGNER,
        *CORRECTION.values(),
        *(
            str(RECEPTION[k])
            for k in (
                "dropped_off_by_name",
                "dropped_off_by_phone",
                "visible_damage",
                "belongings",
            )
        ),
    ]
    assert [value for value in personal if value.lower() in audit] == []


# --- Carreras con dos transacciones reales ----------------------------------------


@pytest_asyncio.fixture
async def racing(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> tuple[Order, StaffMember]:
    """Una orden recibida de A, con 100.000 km a la entrada, y una
    administradora con cuenta."""
    order = await seed_order(engines, two_workshops)
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE work_orders SET odometer_km = 100000 WHERE id = :o"),
            {"o": order.order_id},
        )
    staff = await employee_with_access(
        engines, make_account, order.workshop_id, "admin"
    )
    return order, staff


def sign_paper(
    session: AsyncSession, order: Order, staff: StaffMember
) -> Coroutine[Any, Any, None]:
    return reception_service.sign(
        session,
        order.workshop_id,
        staff.employee_id,
        staff.user_id,
        order.order_id,
        expected_version=1,
        method=SignatureMethod.PAPER,
        signer_name=None,
        signature=None,
    )


def change_to(
    session: AsyncSession,
    order: Order,
    staff: StaffMember,
    to_status: str,
    **extra: Any,
) -> Coroutine[Any, Any, None]:
    return order_service.change_status(
        session,
        order.order_id,
        staff.employee_id,
        "admin",
        expected_version=1,
        to_status=to_status,
        **{"note": None, **extra},
    )


def correct_km(
    session: AsyncSession, order: Order, staff: StaffMember, km: int
) -> Coroutine[Any, Any, None]:
    return order_service.update_order(
        session,
        order.workshop_id,
        staff.user_id,
        order.order_id,
        expected_version=1,
        changes={"odometer_km": km},
    )


async def order_state(engines: Engines, order: Order) -> Any:
    async with engines.platform.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT status, odometer_km, delivered_odometer_km"
                    " FROM work_orders WHERE id = :o"
                ),
                {"o": order.order_id},
            )
        ).one()


def refused(outcome: object, code: str) -> bool:
    return isinstance(outcome, ConflictError) and outcome.code == code


@pytest.mark.asyncio
async def test_signing_while_the_reception_is_corrected_waits_and_is_refused(
    engines: Engines, racing: tuple[Order, StaffMember]
) -> None:
    """La otra mitad de test_reception.py: aquí la corrección va primero. La
    firma espera a la orden y la encuentra con otra versión: la hoja no se
    guarda con unos datos que ya no son los de la orden."""
    order, staff = racing
    async with (
        open_transaction(order.workshop_id) as first,
        open_transaction(order.workshop_id) as second,
    ):
        await correct_km(first, order, staff, 100_500)
        work = asyncio.create_task(sign_paper(second, order, staff))
        await asyncio.sleep(GRACE)
        assert not work.done(), "la firma debería esperar a la corrección"
        await first.commit()
        outcome = await finish(second, work)

    assert refused(outcome, "modified_by_someone_else"), outcome
    assert await sheets_of(engines, order.order_id) == 0


@pytest.mark.asyncio
async def test_signing_while_the_order_is_cancelled_leaves_no_sheet_on_it(
    engines: Engines, racing: tuple[Order, StaffMember]
) -> None:
    order, staff = racing
    async with (
        open_transaction(order.workshop_id) as first,
        open_transaction(order.workshop_id) as second,
    ):
        await change_to(first, order, staff, "cancelled", note="Abierta por error")
        work = asyncio.create_task(sign_paper(second, order, staff))
        await asyncio.sleep(GRACE)
        assert not work.done(), "la firma debería esperar a la cancelación"
        await first.commit()
        outcome = await finish(second, work)

    assert refused(outcome, "modified_by_someone_else"), outcome
    assert (await order_state(engines, order)).status == "cancelled"
    assert await sheets_of(engines, order.order_id) == 0


@pytest.mark.asyncio
async def test_signing_while_the_car_is_delivered_leaves_no_sheet_on_it(
    engines: Engines, racing: tuple[Order, StaffMember]
) -> None:
    order, staff = racing
    await force_status(str(order.order_id), "ready")
    async with (
        open_transaction(order.workshop_id) as first,
        open_transaction(order.workshop_id) as second,
    ):
        await change_to(first, order, staff, "delivered", odometer_km=101_000)
        work = asyncio.create_task(sign_paper(second, order, staff))
        await asyncio.sleep(GRACE)
        assert not work.done(), "la firma debería esperar a la entrega"
        await first.commit()
        outcome = await finish(second, work)

    assert refused(outcome, "modified_by_someone_else"), outcome
    assert (await order_state(engines, order)).status == "delivered"
    assert await sheets_of(engines, order.order_id) == 0


@pytest.mark.asyncio
async def test_delivering_while_the_entry_km_are_raised_is_refused_not_a_500(
    engines: Engines, racing: tuple[Order, StaffMember]
) -> None:
    """Se corrigen los km de entrada a 200.000 mientras se entrega con 150.000
    (que valían contra los 100.000 que leyó quien entrega). La entrega espera y
    se rechaza con un 409; sin las guardas, chocaría con el CHECK (un 500)."""
    order, staff = racing
    await force_status(str(order.order_id), "ready")
    async with (
        open_transaction(order.workshop_id) as first,
        open_transaction(order.workshop_id) as second,
    ):
        await correct_km(first, order, staff, 200_000)
        work = asyncio.create_task(
            change_to(second, order, staff, "delivered", odometer_km=150_000)
        )
        await asyncio.sleep(GRACE)
        assert not work.done(), "la entrega debería esperar a la corrección"
        await first.commit()
        outcome = await finish(second, work)

    assert refused(outcome, "modified_by_someone_else"), outcome
    assert tuple(await order_state(engines, order)) == ("ready", 200_000, None)


@pytest.mark.asyncio
async def test_raising_the_entry_km_while_delivering_is_refused_not_a_500(
    engines: Engines, racing: tuple[Order, StaffMember]
) -> None:
    """Al revés: la entrega va primero. La corrección, que leyó la orden aún
    lista, espera a la fila y se rechaza: una entregada no se edita (RF-26) y
    sus km de entrada no pasan de los de salida."""
    order, staff = racing
    await force_status(str(order.order_id), "ready")
    async with (
        open_transaction(order.workshop_id) as first,
        open_transaction(order.workshop_id) as second,
    ):
        await change_to(first, order, staff, "delivered", odometer_km=150_000)
        work = asyncio.create_task(correct_km(second, order, staff, 200_000))
        await asyncio.sleep(GRACE)
        assert not work.done(), "la corrección debería esperar a la entrega"
        await first.commit()
        outcome = await finish(second, work)

    assert isinstance(outcome, StaleDataError | ConflictError), outcome
    assert tuple(await order_state(engines, order)) == ("delivered", 100_000, 150_000)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "km",
    ["-1", "10000000", '"mucho"', "1.5", "NaN"],
)
async def test_impossible_km_at_delivery_are_a_422(
    client: AsyncClient, shop: Shop, km: str
) -> None:
    order = await open_order(client, shop.headers, shop.car["id"], odometer_km=1000)
    await force_status(order["id"], "ready")
    current = await get(client, shop.headers, order["id"])
    response = await client.post(
        f"{URL}/{order['id']}/status",
        content=(
            f'{{"version": {current["version"]}, "to_status": "delivered",'
            f' "odometer_km": {km}}}'
        ).encode(),
        headers={**shop.headers, "content-type": "application/json"},
    )
    assert response.status_code == 422, response.text
    assert (await get(client, shop.headers, order["id"]))["status"] == "ready"
