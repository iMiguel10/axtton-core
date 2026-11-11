"""Pruebas adversas del cierre de F4 que faltaban (arquitectura §2, §4, §7.2).

- T4 en todas las rutas del portal con un id, leídas del OpenAPI: una ruta nueva
  queda cubierta sola, y una prueba de control falla si trae un id que el barrido
  no sabe rellenar.
- Lo que sale por el portal, buscado en todas sus respuestas a la vez (la ficha
  del cliente, sus vehículos, la orden y el PDF de cada versión).
- Carreras con dos transacciones reales: anonimizar mientras el cliente decide,
  la entrada de la demo mientras le cambian el email, y buscar un nombre corto
  mientras otro taller lo cambia.
- RNF-40 sobre un cliente que entró en el portal, decidió con motivo y después
  se anonimizó, también en la base de SuperTokens.
- Los triggers y el CHECK de F4 con los tres roles.
- Los límites de las rutas sin sesión: que no se esquiven cambiando de ruta, de
  forma de la URL o de X-Forwarded-For.
"""

import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.domain.quotes import Outcome
from app.infra.email import InMemoryEmailSender
from app.infra.rate_limit import (
    LimitsRateLimiter,
    current_rate_limiter,
    set_rate_limiter,
)
from tests.conftest import Engines, TwoWorkshops
from tests.test_adverse_f3 import outcome_of, where
from tests.test_anonymize import PERSONAL, anonymize, dump_of_every_table
from tests.test_anonymize import read as read_client
from tests.test_auth import PUBLIC_ROUTES
from tests.test_clients import create as create_client
from tests.test_clients import open_workshop
from tests.test_concurrency import (
    GRACE,
    dispose_global_engines,  # noqa: F401
    open_transaction,
)
from tests.test_employees import add_mechanic
from tests.test_payment import deliver
from tests.test_portal_auth import add_client, new_email
from tests.test_portal_decision import (
    BROWSER,
    REASON,
    decision_row,
    luis_sent_quote,
    post_decision,
)
from tests.test_portal_demo import demo_email, demo_entry
from tests.test_portal_orders import PORTAL, Portal, enter, portal, workshop_id_of
from tests.test_portal_pdf import CANCEL_REASON, client_pdf
from tests.test_portal_sessions import Shops, can_refresh, shops
from tests.test_portal_sessions import enter as enter_session
from tests.test_quote_decision import decide, sent_order
from tests.test_quote_pdf import text_of
from tests.test_quote_send import cancel, diagnosing_order, draft_with_lines, send
from tests.test_quotes import ORDERS
from tests.test_rls import set_workshops
from tests.test_vehicles import create as create_vehicle
from tests.test_work_orders import Shop, new_shop, outbox
from tests.test_worklog import add_work

__all__ = ["demo_entry", "outbox", "portal", "shops"]

ENTRY = f"{PORTAL}/workshops"


@pytest_asyncio.fixture
async def limiter() -> AsyncIterator[None]:
    """Un limitador real con almacén en memoria, nuevo en cada prueba (las demás
    corren sin límite, conftest.py)."""
    previous = current_rate_limiter()
    set_rate_limiter(LimitsRateLimiter("async+memory://"))
    yield
    set_rate_limiter(previous)


async def scalar(engines: Engines, sql: str, **params: Any) -> Any:
    async with engines.platform.connect() as conn:
        return await conn.scalar(text(sql), params)


# --- T4 en todas las rutas del portal con un id ------------------------------------

PARAM = re.compile(r"\{([^}]+)\}")
# Qué recurso del cliente va en cada parámetro de una ruta del portal. Una ruta
# nueva con otro parámetro hace fallar la prueba de control: hay que decir aquí
# qué es, y así queda en el barrido.
RESOURCE_OF_PARAM = {"order_id": "order", "quote_id": "quote"}
# El cuerpo mínimo válido de cada ruta que lo pide. Sin él, la petición propia de
# control daría un 422 y la prueba fallaría: nadie pasa el barrido con un cuerpo
# que se rechaza antes de llegar a la guarda.
BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("POST", f"{PORTAL}/quotes/{{quote_id}}/decision"): {"outcome": "approved"},
}


def portal_routes_with_ids() -> list[tuple[str, str]]:
    """(método, ruta) de cada operación del portal con sesión y algún id en la
    ruta, del OpenAPI: una ruta nueva queda cubierta sola."""
    from app.main import app

    return [
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith(f"{PORTAL}/") and PARAM.search(path)
        for method in operations
        if (method.upper(), path) not in PUBLIC_ROUTES
    ]


@dataclass(frozen=True)
class Owned:
    """Una orden y una versión enviada de un cliente."""

    order: str
    quote: str

    def fill(self, path: str) -> str:
        return PARAM.sub(lambda m: str(getattr(self, RESOURCE_OF_PARAM[m[1]])), path)


async def call(
    client: AsyncClient,
    method: str,
    path: str,
    headers: dict[str, str],
    ids: Owned,
) -> Response:
    return await client.request(
        method, ids.fill(path), json=BODIES.get((method, path)), headers=headers
    )


def test_the_t4_sweep_knows_every_id_of_the_portal() -> None:
    """Prueba de control: si el barrido no encontrara rutas, o una trajera un id
    que no sabe rellenar, T4 pasaría sin probar nada."""
    routes = portal_routes_with_ids()
    assert len(routes) >= 3, routes
    params = {name for _, path in routes for name in PARAM.findall(path)}
    assert params - set(RESOURCE_OF_PARAM) == set()


@pytest.mark.asyncio
async def test_t4_no_portal_route_with_an_id_reaches_what_is_not_the_clients(
    client: AsyncClient,
    portal: Portal,
    engines: Engines,
    outbox: InMemoryEmailSender,
) -> None:
    """María (taller A) contra lo de Luis (A) y lo de su gemela en B, con el mismo
    email; la de B contra lo de María en A. Siempre un 404 idéntico al de un id
    que no existe, y nada cambia. Después, las mismas rutas con lo suyo responden
    bien: el 404 era el aislamiento, no una ruta o un cuerpo inválidos."""
    shop = portal.shop
    maria_a = Owned(*await sent_order(client, shop))
    luis_a = Owned(*await luis_sent_quote(client, shop))
    maria_email = (await read_client(client, shop.headers, shop.maria["id"]))["email"]
    other = await open_workshop(client, "Taller B")
    twin = await create_client(client, other.headers, name="María", email=maria_email)
    car = await create_vehicle(client, other.headers, twin["id"], make="Opel")
    maria_b = Owned(*await sent_order(client, Shop(other, twin, twin, car)))
    twin_session = await enter(
        client, outbox, UUID(other.invited.workshop_id), maria_email
    )
    nobody = Owned(str(uuid4()), str(uuid4()))

    routes = portal_routes_with_ids()
    attacks = [
        ("María contra Luis", portal.maria, luis_a),
        ("María contra su gemela de B", portal.maria, maria_b),
        ("la gemela de B contra María", twin_session, maria_a),
    ]
    for method, path in routes:
        for who, headers, theirs in attacks:
            response = await call(client, method, path, headers, theirs)
            missing = await call(client, method, path, headers, nobody)
            assert response.status_code == 404, (who, method, path, response.text)
            assert response.json() == missing.json(), (who, method, path)

    for theirs in (maria_a, luis_a, maria_b):
        assert await decision_row(engines, theirs.quote) is None
        assert (
            await scalar(
                engines, "SELECT status FROM quotes WHERE id = :q", q=theirs.quote
            )
            == "sent"
        )

    for method, path in routes:
        for headers, own in ((portal.maria, maria_a), (twin_session, maria_b)):
            response = await call(client, method, path, headers, own)
            assert response.status_code < 300, (method, path, response.text)


# --- Lo que sale por el portal ---------------------------------------------------------

INTERNAL_NOTE = "NOTA-INTERNA el cliente regatea siempre"
CLIENT_NOTES = "FICHA-INTERNA no fiarle nunca"
DECISION_NOTE = "NOTA-DE-LA-DECISION lo dijo de mala gana"


@pytest.mark.asyncio
async def test_rf43_nothing_internal_reaches_the_client_on_any_portal_route(
    client: AsyncClient, portal: Portal, engines: Engines
) -> None:
    """Todo lo que el cliente puede leer de una orden con historia (una nota
    interna, un trabajo con sus horas y su mecánico, una versión anulada con su
    motivo y otra aceptada por teléfono con nota), junto: su ficha, sus
    vehículos, la orden y el PDF de cada versión. Se busca en el texto entero,
    no campo a campo: lo que preocupa es lo que nadie pensó en quitar."""
    shop = portal.shop
    maria = await read_client(client, shop.headers, shop.maria["id"])
    patched = await client.patch(
        f"/api/v1/workshop/clients/{maria['id']}",
        json={"version": maria["version"], "notes": CLIENT_NOTES},
        headers=shop.headers,
    )
    assert patched.status_code == 204, patched.text
    mechanic = await add_mechanic(client, shop.admin, "Juanísimo Escondido")
    order_id = await diagnosing_order(client, shop)
    note = await client.post(
        f"{ORDERS}/{order_id}/notes", json={"body": INTERNAL_NOTE}, headers=shop.headers
    )
    assert note.status_code == 201, note.text
    work = await add_work(
        client, shop.headers, order_id, mechanic, hours="7.25", description="Aceite"
    )
    assert work.status_code == 201, work.text
    first = await draft_with_lines(client, shop, order_id)
    assert (await send(client, shop, order_id, first)).status_code == 204
    assert (
        await cancel(client, shop, order_id, first, CANCEL_REASON)
    ).status_code == 204
    second = await draft_with_lines(client, shop, order_id)
    assert (await send(client, shop, order_id, second)).status_code == 204
    decided = await decide(client, shop, order_id, second, note=DECISION_NOTE)
    assert decided.status_code == 204, decided.text

    responses = [
        await client.get(f"{PORTAL}/me", headers=portal.maria),
        await client.get(f"{PORTAL}/vehicles", headers=portal.maria),
        await client.get(f"{PORTAL}/orders/{order_id}", headers=portal.maria),
    ]
    for response in responses:
        assert response.status_code == 200, response.text
    seen = "\n".join(
        [r.text for r in responses]
        + [text_of(await client_pdf(client, portal.maria, q)) for q in (first, second)]
    ).lower()

    # Lo que sí debe estar: sin esto, la búsqueda podría no mirar nada.
    for expected in ("aceite", "anulado por el taller", "aceptado por el cliente"):
        assert expected in seen, expected
    async with engines.platform.connect() as conn:
        staff = (
            await conn.scalars(
                text("SELECT name FROM employees WHERE workshop_id = :w"),
                {"w": workshop_id_of(shop)},
            )
        ).all()
    assert len(staff) >= 2  # la administradora y el mecánico
    for secret in (
        *staff,
        INTERNAL_NOTE,
        CLIENT_NOTES,
        CANCEL_REASON,
        DECISION_NOTE,
        "registrada por",
        "hourly_cost",
        "recorded_by",
    ):
        assert secret.lower() not in seen, secret
    # Las horas del trabajo, como número suelto: "7.25" también puede salir por azar
    # dentro de una fecha (los segundos de "…:57.254"), y la prueba fallaba a veces.
    assert not re.search(r"(?<![d.,:])7[.,]25(?!d)", seen), "las horas del trabajo"


# --- Carreras con dos transacciones reales -------------------------------------------


async def admin_user(engines: Engines, workshop_id: UUID) -> UUID:
    found = await scalar(
        engines,
        "SELECT user_id FROM employees WHERE workshop_id = :w AND role = 'admin'"
        " AND user_id IS NOT NULL LIMIT 1",
        w=workshop_id,
    )
    return UUID(str(found))


async def decide_as_the_portal_does(
    session: AsyncSession,
    workshop_id: UUID,
    client_id: UUID,
    quote_id: UUID,
    portal_epoch: int,
) -> None:
    """Lo que hace una petición de decisión del portal, en una transacción que
    controla la prueba: comprobar la sesión (`portal_context`) y decidir."""
    from app.services import portal_auth as portal_auth_service
    from app.services import quotes as quote_service

    await portal_auth_service.current_client(
        session,
        workshop_id,
        client_id,
        portal_epoch=portal_epoch,
        expires_at=int((datetime.now(UTC) + timedelta(days=1)).timestamp()),
    )
    await quote_service.decide_from_portal(
        session,
        workshop_id,
        client_id,
        quote_id,
        outcome=Outcome.REJECTED,
        reason=REASON,
        ip="203.0.113.9",
        user_agent=BROWSER,
    )


@pytest.mark.asyncio
async def test_anonymizing_while_the_client_decides_never_leaves_its_ip_behind(
    client: AsyncClient, portal: Portal, engines: Engines
) -> None:
    """RNF-40 con dos transacciones: anonimizar no espera a nada que ponga en fila
    una decisión del portal (bloquea al cliente; la decisión, la orden), así que si
    anonimizar pudiera confirmarse con la decisión en vuelo, esta llegaría después
    del borrado y su IP, su navegador y su motivo se quedarían para siempre. Lo
    impide que no se pueda anonimizar con una orden abierta, y una versión solo se
    decide con la orden abierta."""
    from app.services import clients as client_service

    shop = portal.shop
    a = workshop_id_of(shop)
    _, quote_id = await sent_order(client, shop)
    maria_id = UUID(shop.maria["id"])
    version = await scalar(
        engines, "SELECT version FROM clients WHERE id = :c", c=maria_id
    )
    epoch = await scalar(
        engines, "SELECT portal_epoch FROM clients WHERE id = :c", c=maria_id
    )
    user_id = await admin_user(engines, a)

    refusal: ConflictError | None = None
    async with open_transaction(a) as first, open_transaction(a) as second:
        try:
            await client_service.anonymize_client(
                first, a, user_id, maria_id, expected_version=version
            )
        except ConflictError as error:
            refusal = error
        work = asyncio.create_task(
            decide_as_the_portal_does(second, a, maria_id, UUID(quote_id), epoch)
        )
        await asyncio.sleep(GRACE)
        if refusal is None:
            await first.commit()
        else:
            await first.rollback()
        outcome = await outcome_of(second, work)

    anonymized = await scalar(
        engines,
        "SELECT anonymized_at IS NOT NULL FROM clients WHERE id = :c",
        c=maria_id,
    )
    row = await decision_row(engines, quote_id)
    left = row is not None and any(row[k] for k in ("ip", "user_agent", "note"))
    assert not (anonymized and left), f"anonimizada y con {row} ({where(outcome)})"
    # Y lo que pasa de verdad: anonimizar se niega, la decisión vale entera.
    assert refusal is not None and refusal.code == "client_has_open_orders"
    assert outcome is None, where(outcome)
    assert row is not None and row["ip"] == "203.0.113.9"


@pytest.mark.asyncio
async def test_the_demo_entry_waits_for_an_email_change_and_does_not_enter(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    demo_entry: None,
) -> None:
    """La entrada de la demo emite y consume un enlace en el acto. Si le cambian el
    email al cliente a la vez, emitir espera al cambio (el cliente bloqueado en
    compartido) y después ya no lo encuentra con el email de antes: ni sesión, ni
    un enlace abierto. Sin el bloqueo, entraría con el email que acaba de dejar de
    ser suyo."""
    from app.services import clients as client_service
    from app.services import portal_auth as portal_auth_service

    a = two_workshops.a
    email = demo_email("carmen")
    client_id = await add_client(engines, a, email)
    version = await scalar(
        engines, "SELECT version FROM clients WHERE id = :c", c=client_id
    )

    async with open_transaction(a) as first:
        previous = await client_service.update_client(
            first,
            client_id,
            expected_version=version,
            changes={"email": demo_email("otra")},
        )
        assert previous == email
        work = asyncio.create_task(portal_auth_service.demo_login(a, email))
        await asyncio.sleep(GRACE)
        assert not work.done(), "emitir debería esperar al cambio de email"
        await first.commit()
    try:
        outcome: object = await asyncio.wait_for(work, timeout=10)
    except Exception as error:  # noqa: BLE001 - es lo que se quiere mirar
        outcome = error

    assert isinstance(outcome, NotFoundError), where(outcome)
    assert outcome.code == "demo_client_not_found"
    open_links = await scalar(
        engines,
        "SELECT count(*) FROM portal_links WHERE used_at IS NULL AND revoked_at IS NULL",
    )
    assert open_links == 0


@pytest.mark.asyncio
async def test_looking_up_a_name_while_its_workshop_changes_it_never_waits(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    """Buscar un taller por su nombre corto es una sola lectura, sin bloqueos: con
    un cambio a medias, la entrada sigue llevando al taller por el nombre viejo
    (no espera al administrador ni da un error) y, confirmado, por el nuevo."""
    from app.platform.portal_entry import workshop_id_by_slug

    a = two_workshops.a
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE workshops SET portal_slug = 'nombre-viejo' WHERE id = :w"),
            {"w": a},
        )

    async with open_transaction(a) as first:
        await first.execute(
            text("UPDATE workshops SET portal_slug = 'nombre-nuevo' WHERE id = :w"),
            {"w": a},
        )
        during = await asyncio.wait_for(
            asyncio.gather(
                workshop_id_by_slug("nombre-viejo"), workshop_id_by_slug("nombre-nuevo")
            ),
            timeout=GRACE * 4,
        )
        await first.commit()
    after = (
        await workshop_id_by_slug("nombre-viejo"),
        await workshop_id_by_slug("nombre-nuevo"),
    )

    assert during == [a, None]
    assert after == (None, a)


# --- RNF-40: un cliente que usó el portal, anonimizado --------------------------------


@pytest.mark.asyncio
async def test_rnf40_a_client_who_used_the_portal_leaves_nothing_after_anonymizing(
    client: AsyncClient, engines: Engines, outbox: InMemoryEmailSender
) -> None:
    """María, con todos sus datos, entra en el portal, rechaza con motivo desde su
    móvil y, ya entregado el coche, pide que la borren. Después no queda nada suyo
    en ninguna tabla (el barrido de test_anonymize.py), su sesión ya no vale, y
    SuperTokens ya no guarda su email (el usuario passwordless se borra al no
    quedarle sesiones)."""
    from supertokens_python.asyncio import list_users_by_account_info
    from supertokens_python.types.base import AccountInfoInput

    shop = await new_shop(client)
    email = new_email()
    personal = {**PERSONAL, "email": email}
    patched = await client.patch(
        f"/api/v1/workshop/clients/{shop.maria['id']}",
        json={"version": shop.maria["version"], **personal},
        headers=shop.headers,
    )
    assert patched.status_code == 204, patched.text
    session = await enter(client, outbox, workshop_id_of(shop), email)
    order_id, quote_id = await sent_order(client, shop)
    rejected = await post_decision(client, session, quote_id, "rejected", REASON)
    assert rejected.status_code == 204, rejected.text
    before = await decision_row(engines, quote_id)
    assert before is not None and before["ip"] and before["note"] == REASON
    users = await list_users_by_account_info("public", AccountInfoInput(email=email))
    assert any(m.recipe_id == "passwordless" for u in users for m in u.login_methods)
    await deliver(order_id)

    maria = await read_client(client, shop.headers, shop.maria["id"])
    assert (await anonymize(client, shop.headers, maria)).status_code == 204

    dump = await dump_of_every_table()
    for value in (*personal.values(), BROWSER, REASON, before["ip"]):
        assert str(value).lower() not in dump, value
    assert (await client.get(f"{PORTAL}/me", headers=session)).status_code == 401
    users = await list_users_by_account_info("public", AccountInfoInput(email=email))
    assert not any(
        m.recipe_id == "passwordless" for u in users for m in u.login_methods
    ), users


@pytest.mark.asyncio
async def test_t7_entering_another_workshop_while_one_is_closed_keeps_that_session(
    client: AsyncClient,
    shops: Shops,
    outbox: InMemoryEmailSender,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`revoke_client_sessions` lee las sesiones del usuario, cierra las de A y, si
    eran todas, borra el usuario. Si el mismo email entra en B entre leerlas y
    borrarlo (el usuario passwordless es uno por email), esa sesión nueva no
    estaba en la lista, y borrar el usuario se la lleva: T7 dice que la de B sigue
    viva. Se intercala la entrada en B justo después de leer la lista."""
    from app.core import sessions

    email = new_email()
    in_a = await create_client(client, shops.a.headers, email=email)
    await create_client(client, shops.b.headers, email=email)
    await enter_session(client, outbox, shops.id_a, email)

    real = sessions.get_session_information
    entered: list[Response] = []

    async def b_enters_meanwhile(handle: str) -> Any:
        if not entered:
            entered.append(await enter_session(client, outbox, shops.id_b, email))
        return await real(handle)

    monkeypatch.setattr(sessions, "get_session_information", b_enters_meanwhile)
    await sessions.revoke_client_sessions(email, shops.id_a, UUID(in_a["id"]))
    monkeypatch.undo()

    (session_b,) = entered
    assert await can_refresh(client, session_b), "la sesión de B se cerró con la de A"


# --- Los triggers y el CHECK de F4 con los tres roles ---------------------------------

ERASE = (
    "UPDATE quote_decisions SET ip = NULL, user_agent = NULL, note = NULL"
    " WHERE quote_id = :q"
)


async def run_as(
    engine: AsyncEngine, workshop_id: UUID, sql: str, **params: Any
) -> int:
    """Una sentencia con el taller fijado (el dueño también obedece RLS: sin taller
    no vería la fila y no probaría nada). Devuelve las filas tocadas."""
    async with engine.begin() as conn:
        await set_workshops(conn, workshop_id)
        result = await conn.execute(text(sql), params)
    return int(result.rowcount)  # type: ignore[attr-defined]


def role_engine(engines: Engines, role: str) -> AsyncEngine:
    engine: AsyncEngine = getattr(engines, role)
    return engine


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "refusal"),
    [("platform", "permission denied"), ("owner", "cannot change")],
)
async def test_no_role_erases_a_portal_decision_of_a_client_not_anonymized(
    client: AsyncClient, portal: Portal, engines: Engines, role: str, refusal: str
) -> None:
    """La excepción de 0018decisionerase es solo para un cliente ya anonimizado,
    también para el dueño de las tablas (la de la aplicación, en
    test_portal_decision.py). La plataforma ni siquiera tiene el permiso."""
    _, quote_id = await sent_order(client, portal.shop)
    rejected = await post_decision(client, portal.maria, quote_id, "rejected", REASON)
    assert rejected.status_code == 204, rejected.text

    with pytest.raises(DBAPIError, match=refusal):
        await run_as(
            role_engine(engines, role), workshop_id_of(portal.shop), ERASE, q=quote_id
        )
    row = await decision_row(engines, quote_id)
    assert row is not None and row["note"] == REASON and row["ip"]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "owner"])
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE quote_decisions SET note = 'reescrito' WHERE quote_id = :q",
        "UPDATE quote_decisions SET ip = '198.51.100.1' WHERE quote_id = :q",
        "UPDATE quote_decisions SET user_agent = 'otro' WHERE quote_id = :q",
    ],
)
async def test_once_erased_nobody_writes_into_the_decision_again(
    client: AsyncClient, portal: Portal, engines: Engines, role: str, statement: str
) -> None:
    """Vaciadas al anonimizar, la IP, el navegador y el motivo no se vuelven a
    escribir: la excepción del trigger es vaciarlas, no editarlas. La aplicación
    tiene permiso sobre esas tres columnas, así que lo que la para es el trigger."""
    _, quote_id = await sent_order(client, portal.shop)
    rejected = await post_decision(client, portal.maria, quote_id, "rejected", REASON)
    assert rejected.status_code == 204, rejected.text
    await deliver(
        await scalar(
            engines, "SELECT work_order_id FROM quotes WHERE id = :q", q=quote_id
        )
    )
    maria = await read_client(client, portal.shop.headers, portal.shop.maria["id"])
    assert (await anonymize(client, portal.shop.headers, maria)).status_code == 204

    with pytest.raises(DBAPIError, match="cannot change"):
        await run_as(
            role_engine(engines, role),
            workshop_id_of(portal.shop),
            statement,
            q=quote_id,
        )
    row = await decision_row(engines, quote_id)
    assert row is not None
    assert (row["ip"], row["user_agent"], row["note"]) == (None, None, None)


BAD_SLUGS = [
    "Mayusculas",
    "ab",
    "-delante",
    "detras-",
    "dos--guiones",
    "con espacio",
    "ñandu",
    "punto.com",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform", "owner"])
async def test_no_role_stores_a_name_that_is_not_an_address(
    engines: Engines, two_workshops: TwoWorkshops, role: str
) -> None:
    """El CHECK de 0019portalslug para todos, no solo lo que comprueba la API:
    "sin distinguir mayúsculas" solo es "igual" si nadie guarda una mayúscula. Uno
    válido sí se guarda con cada rol: la negativa es el CHECK, no un permiso. Más
    de 40 caracteres ya los para antes el tipo de la columna, varchar(40)."""
    engine = role_engine(engines, role)
    a = two_workshops.a
    set_slug = "UPDATE workshops SET portal_slug = :s WHERE id = :w"
    for slug in BAD_SLUGS:
        with pytest.raises(DBAPIError, match="ck_workshops_portal_slug"):
            await run_as(engine, a, set_slug, s=slug, w=a)
    assert await run_as(engine, a, set_slug, s=f"taller-{role}", w=a) == 1


@pytest.mark.asyncio
async def test_the_app_cannot_take_or_read_the_name_of_another_workshop(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    """Solo la vía de plataforma con nombre (decisión 0007) mira otros talleres:
    con A fijado, el nombre de B ni se ve ni se cambia (RLS en `workshops`)."""
    a, b = two_workshops.a, two_workshops.b
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE workshops SET portal_slug = 'el-de-b' WHERE id = :w"),
            {"w": b},
        )
    changed = await run_as(
        engines.app,
        a,
        "UPDATE workshops SET portal_slug = 'robado' WHERE id = :w",
        w=b,
    )
    assert changed == 0
    async with engines.app.begin() as conn:
        await set_workshops(conn, a)
        seen = await conn.scalar(
            text("SELECT count(*) FROM workshops WHERE portal_slug = 'el-de-b'")
        )
    assert seen == 0
    assert (
        await scalar(engines, "SELECT portal_slug FROM workshops WHERE id = :w", w=b)
        == "el-de-b"
    )


# --- Las rutas sin sesión: límites que no se esquivan ---------------------------------


def limited(response: Response) -> bool:
    """Un 429 de verdad, con su código. Mirando el estado antes que el cuerpo: un
    202 o un 204 sin cuerpo no debe convertirse en un TypeError."""
    return response.status_code == 429 and response.json()["code"] == "rate_limited"


@pytest.mark.asyncio
async def test_the_demo_list_counts_with_the_other_entry_pages(
    client: AsyncClient,
    two_workshops: TwoWorkshops,
    limiter: None,
    demo_entry: None,
) -> None:
    """La lista de la demo también es una página sin sesión: cuenta con el nombre,
    el logotipo y la búsqueda por nombre corto, así que no sirve para seguir
    probando nombres cuando las otras ya están frenadas."""
    a = two_workshops.a
    for _ in range(60):
        assert (await client.get(f"{ENTRY}/{a}/demo-clients")).status_code == 200
    for path in (
        f"{ENTRY}/by-slug/otro-nombre",
        f"{ENTRY}/{a}",
        f"{ENTRY}/{a}/logo",
        f"{ENTRY}/{a}/demo-clients",
    ):
        response = await client.get(path)
        assert limited(response), (path, response.status_code, response.text)


@pytest.mark.asyncio
async def test_the_demo_entry_counts_with_consuming_links(
    client: AsyncClient,
    two_workshops: TwoWorkshops,
    limiter: None,
    demo_entry: None,
) -> None:
    """Entrar en la demo da una sesión, como consumir un enlace: comparten el
    límite por IP, y agotado uno, el otro tampoco abre nada."""
    body = {"workshop_id": str(two_workshops.a), "token": "no-existe"}
    for _ in range(30):
        assert (
            await client.post(f"{PORTAL}/auth/consume", json=body)
        ).status_code == 400
    response = await client.post(
        f"{PORTAL}/auth/demo-enter",
        json={"workshop_id": str(two_workshops.a), "email": demo_email("nadie")},
    )
    assert limited(response), (response.status_code, response.text)


@pytest.mark.asyncio
async def test_a_forged_forwarded_for_does_not_skip_the_portal_limits(
    client: AsyncClient, limiter: None
) -> None:
    """Sin proxies de confianza, X-Forwarded-For no cuenta: inventarse una IP por
    petición no da 20 enlaces más."""
    workshop = str(uuid4())
    for i in range(20):
        response = await client.post(
            f"{PORTAL}/auth/request-link",
            json={"workshop_id": workshop, "email": new_email()},
            headers={"X-Forwarded-For": f"198.51.100.{i}"},
        )
        assert response.status_code == 202
    response = await client.post(
        f"{PORTAL}/auth/request-link",
        json={"workshop_id": workshop, "email": new_email()},
        headers={"X-Forwarded-For": "198.51.100.250"},
    )
    assert limited(response), (response.status_code, response.text)


@pytest.mark.asyncio
async def test_another_spelling_of_the_url_never_sends_a_link_past_the_limit(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    outbox: InMemoryEmailSender,
    limiter: None,
) -> None:
    """El límite del portal vive en el endpoint, no en un middleware que mire la
    ruta: una forma rara de la URL o no llega al endpoint, o pasa por el límite.
    Agotado el de un email, ninguna variante consigue que salga otro enlace."""
    email = new_email()
    await add_client(engines, two_workshops.a, email)
    body = {"workshop_id": str(two_workshops.a), "email": email}
    for _ in range(5):
        assert (
            await client.post(f"{PORTAL}/auth/request-link", json=body)
        ).status_code == 202
    sent = len(outbox.sent)
    assert sent == 5

    for path in (
        f"{PORTAL}/auth/request-link/",
        f"{PORTAL}/auth/request-link;x",
        f"{PORTAL}/auth/Request-Link",
        "/api/v1//portal/auth/request-link",
        f"{PORTAL}/auth/./request-link",
        f"{PORTAL}/auth/request-link?email=otro@example.com",
    ):
        response = await client.post(path, json=body, follow_redirects=True)
        assert response.status_code in (404, 405, 429), (path, response.status_code)
    assert len(outbox.sent) == sent
