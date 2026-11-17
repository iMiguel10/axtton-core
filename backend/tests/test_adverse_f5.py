"""Pruebas adversas del cierre de F5 que faltaban (arquitectura §4 y §8).

- La bandeja de avisos entre talleres: el mismo motivo en dos talleres son dos
  avisos, y cada pasada del worker toca solo los de su taller; un aviso de A no
  puede apuntar a un cliente, una orden ni una versión de B.
- Los triggers de F5 con los tres roles: `notifications_transitions` (los
  estados finales, de qué y para quién es el aviso, los intentos y el borrado) y
  `quotes_expire_only_when_overdue`.
- Carreras con dos transacciones reales (nunca `asyncio.gather` sobre la API):
  el despachador mientras el taller deshace "lista", deshacer mientras el correo
  está en vuelo, anular mientras sale el aviso de esa versión, y caducar una
  versión mientras se decide o se anula.
- El enlace del portal por el worker: lo encolado no delata nada (RF-41) y el
  error que guarda SAQ no lleva el email.
- RNF-40: la bandeja no guarda el email, el nombre ni el texto del correo, y el
  barrido de anonimizar con avisos ya enviados.
"""

import asyncio
import logging
import os
import traceback
from typing import Any, cast
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.db import workshop_transaction
from app.domain.notifications import (
    FailureReason,
    NotificationStatus,
    ready_key,
)
from app.domain.quotes import DecisionChannel, Outcome, QuoteStatus
from app.infra.email import (
    EmailDeliveryUnknownError,
    EmailNotSentError,
    InMemoryEmailSender,
)
from app.infra.queue import InMemoryJobQueue
from app.jobs.context import WorkerContext
from app.jobs.portal import send_portal_link
from app.repositories import notifications as notification_repo
from app.services import notifications as notification_service
from app.services import quotes as quote_service
from app.services import work_orders as order_service
from app.services.notice_composers import COMPOSERS
from app.services.notifications import NotDelivered
from app.services.portal_auth import LinkNotSentError
from tests.conftest import Engines, TwoWorkshops
from tests.test_anonymize import (
    PERSONAL,
    anonymize,
    dump_of_every_table,
    maria_with_history,
)
from tests.test_anonymize import read as read_client
from tests.test_clients import create as create_client
from tests.test_clients import open_workshop
from tests.test_concurrency import (
    GRACE,
    MakeAccount,
    dispose_global_engines,  # noqa: F401 (autouse)
    open_transaction,
)
from tests.test_notice_log import notices_of
from tests.test_notifications import (
    COMPOSERS as FAKE_COMPOSERS,
)
from tests.test_notifications import (
    KIND,
    FailingSender,
    SlowSender,
    age,
    claimed,
    client_a,
    create,
    row,
)
from tests.test_payment import deliver as deliver_order
from tests.test_portal_auth import add_client, new_email
from tests.test_portal_link_job import Refusing, queue
from tests.test_portal_link_job import request_link as request_link_status
from tests.test_quote_decision import sent_order, sent_quote
from tests.test_quote_notices import deliver_due, notices, set_client, workshop_of
from tests.test_quote_send import cancel
from tests.test_quotes import expire_by_sql
from tests.test_ready_notice import last_seq, ready_order
from tests.test_rls import set_workshops
from tests.test_rls_tables import Seeded, seeded
from tests.test_vehicles import create as create_vehicle
from tests.test_work_order_lifecycle import undo
from tests.test_work_orders import Shop, get, outbox, shop

__all__ = ["client_a", "outbox", "queue", "seeded", "shop"]

ROLES = ["app", "platform", "owner"]


async def scalar(engines: Engines, sql: str, **params: Any) -> Any:
    async with engines.platform.connect() as conn:
        return await conn.scalar(text(sql), params)


async def status_of_notice(engines: Engines, notification_id: UUID) -> str:
    return str((await row(engines, notification_id))["status"])


async def admin_of(engines: Engines, workshop_id: UUID) -> tuple[UUID, UUID]:
    """El empleado administrador del taller y su usuario."""
    async with engines.platform.connect() as conn:
        found = (
            await conn.execute(
                text(
                    "SELECT id, user_id FROM employees"
                    " WHERE workshop_id = :w AND role = 'admin' LIMIT 1"
                ),
                {"w": workshop_id},
            )
        ).one()
    return found.id, found.user_id


async def notice_id(engines: Engines, workshop_id: UUID, key: str) -> UUID:
    found = await scalar(
        engines,
        "SELECT id FROM notifications WHERE workshop_id = :w AND dedupe_key = :k",
        w=workshop_id,
        k=key,
    )
    assert isinstance(found, UUID)
    return found


async def jobs_of_one_pass(workshop_id: UUID) -> list[tuple[UUID, int]]:
    """Una pasada del despachador: (aviso, intento) de lo que encoló."""
    queue = InMemoryJobQueue()
    await notification_service.dispatch(workshop_id, queue, email_enabled=True)
    return [
        (
            UUID(cast(str, job.kwargs["notification_id"])),
            cast(int, job.kwargs["attempt"]),
        )
        for job in queue.jobs
    ]


# --- La bandeja entre talleres ------------------------------------------------------

SAME_KEY = "quote_sent:mismo-motivo"


@pytest_asyncio.fixture
async def twin_notices(
    engines: Engines, two_workshops: TwoWorkshops
) -> tuple[UUID, UUID]:
    """El mismo motivo en A y en B (la clave es única por taller, no en toda la
    instalación). Devuelve el aviso de A y el de B."""
    of_a = await create(
        two_workshops.a,
        await add_client(engines, two_workshops.a, new_email()),
        SAME_KEY,
    )
    of_b = await create(
        two_workshops.b,
        await add_client(engines, two_workshops.b, new_email()),
        SAME_KEY,
    )
    return of_a, of_b


async def pass_in_a(operation: str, a: UUID) -> int:
    if operation == "dispatch":
        return await notification_service.dispatch(
            a, InMemoryJobQueue(), email_enabled=True
        )
    if operation == "skip":
        return await notification_service.dispatch(
            a, InMemoryJobQueue(), email_enabled=False
        )
    if operation == "cancel":
        async with workshop_transaction([a]) as session:
            return await notification_repo.cancel_open(
                session, SAME_KEY, FailureReason.OBSOLETE
            )
    assert operation == "abandoned"
    return await notification_service.expire_abandoned(a)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "after"),
    [
        ("dispatch", "claimed"),
        ("skip", "skipped"),
        ("cancel", "cancelled"),
        ("abandoned", "unknown"),
    ],
)
async def test_each_pass_of_the_worker_touches_only_its_workshop_s_notices(
    engines: Engines,
    two_workshops: TwoWorkshops,
    twin_notices: tuple[UUID, UUID],
    operation: str,
    after: str,
) -> None:
    """Invariante 1 en la bandeja: con el mismo motivo en los dos talleres, lo
    que hace el worker con el taller A fijado (reclamar, omitir, cancelar por
    motivo, dar por abandonado) no toca el aviso de B."""
    of_a, of_b = twin_notices
    if operation == "abandoned":
        for workshop_id, notification_id in (
            (two_workshops.a, of_a),
            (two_workshops.b, of_b),
        ):
            assert await notification_service.dispatch(
                workshop_id, InMemoryJobQueue(), email_enabled=True
            )
            await age(engines, notification_id, "claimed_at", "11 minutes")
    before_b = await row(engines, of_b)

    assert await pass_in_a(operation, two_workshops.a) == 1

    assert await status_of_notice(engines, of_a) == after
    assert await row(engines, of_b) == before_b


@pytest.mark.asyncio
async def test_the_dispatcher_enqueues_each_notice_with_its_own_workshop(
    two_workshops: TwoWorkshops, twin_notices: tuple[UUID, UUID]
) -> None:
    """El trabajo de envío fija el taller que le pasa el despachador: si llevara
    otro, el aviso no se vería (B2) y no saldría nunca."""
    of_a, of_b = twin_notices
    for workshop_id, own in ((two_workshops.a, of_a), (two_workshops.b, of_b)):
        queue = InMemoryJobQueue()
        assert await notification_service.dispatch(
            workshop_id, queue, email_enabled=True
        )
        [job] = queue.jobs
        assert (job.kwargs["workshop_id"], job.kwargs["notification_id"]) == (
            str(workshop_id),
            str(own),
        )


@pytest.mark.asyncio
async def test_the_state_of_a_reason_is_read_only_in_the_workshop_fixed(
    two_workshops: TwoWorkshops, twin_notices: tuple[UUID, UUID]
) -> None:
    """`status_of_key` (lo que mira el aviso de anulación) con la misma clave en
    los dos talleres: sin RLS daría dos filas y lanzaría; con ella, la de A."""
    await notification_service.dispatch(
        two_workshops.b, InMemoryJobQueue(), email_enabled=True
    )
    async with workshop_transaction([two_workshops.a]) as session:
        assert await notification_repo.status_of_key(session, SAME_KEY) == "pending"
    async with workshop_transaction([two_workshops.b]) as session:
        assert await notification_repo.status_of_key(session, SAME_KEY) == "claimed"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform"])
@pytest.mark.parametrize("column", ["client_id", "work_order_id", "quote_id"])
async def test_a_notice_of_a_cannot_point_at_a_client_order_or_quote_of_b(
    engines: Engines, seeded: Seeded, role: str, column: str
) -> None:
    """Las FK compuestas: aunque un fallo del código lo intentara, un aviso de A
    nunca va a un cliente de B ni habla de una orden o una versión de B, así que
    ningún compositor puede escribirle a quien no es de su taller. Tampoco la
    plataforma, que se salta RLS."""
    a, b = seeded.workshops.a, seeded.workshops.b
    of_b = {
        "client_id": await scalar(
            engines, "SELECT id FROM clients WHERE workshop_id = :w LIMIT 1", w=b
        ),
        "work_order_id": await scalar(
            engines, "SELECT id FROM work_orders WHERE workshop_id = :w LIMIT 1", w=b
        ),
        "quote_id": await scalar(
            engines, "SELECT id FROM quotes WHERE workshop_id = :w LIMIT 1", w=b
        ),
    }
    client_of_a = await scalar(
        engines, "SELECT id FROM clients WHERE workshop_id = :w LIMIT 1", w=a
    )
    values = {"client_id": client_of_a, "work_order_id": None, "quote_id": None}
    values[column] = of_b[column]
    async with getattr(engines, role).connect() as conn:
        await set_workshops(conn, a)
        with pytest.raises(DBAPIError, match=f"fk_notifications_{column}_workshop_id"):
            await conn.execute(
                text(
                    "INSERT INTO notifications (workshop_id, kind, dedupe_key,"
                    " client_id, work_order_id, quote_id)"
                    " VALUES (:w, 'quote_sent', 'quote_sent:de-b', :client_id,"
                    " :work_order_id, :quote_id)"
                ),
                {"w": a, **values},
            )
        await conn.rollback()


@pytest.mark.asyncio
async def test_one_email_in_two_workshops_gets_each_notice_from_its_own_workshop(
    client: AsyncClient, shop: Shop, engines: Engines
) -> None:
    """La misma persona es cliente de dos talleres con el mismo email, y los dos
    le avisan de que su coche está listo. Cada correo sale de la pasada de su
    taller, con su nombre y el botón a su portal y a su orden: nada del otro."""
    shared = "persona.compartida@example.com"
    await set_client(engines, shop, email=shared)
    admin_b = await open_workshop(client, "Taller Bermejo")
    maria_b = await create_client(client, admin_b.headers, name="María", email=shared)
    car_b = await create_vehicle(client, admin_b.headers, maria_b["id"], make="Seat")
    shop_b = Shop(admin_b, maria_b, maria_b, car_b)

    sent: dict[str, tuple[UUID, str, Any]] = {}
    for name, own in (("Talleres Pérez", shop), ("Taller Bermejo", shop_b)):
        order = await ready_order(client, own)
        workshop_id = await workshop_of(engines, order["id"])
        [email] = (await deliver_due(workshop_id)).sent
        sent[name] = (workshop_id, order["id"], email)

    for name, (workshop_id, order_id, email) in sent.items():
        [(other_name, (other_workshop, other_order, _))] = [
            item for item in sent.items() if item[0] != name
        ]
        assert email.to == shared
        assert name in email.body and other_name not in email.body
        assert f"/portal/login/{workshop_id}?order={order_id}" in email.body
        assert str(other_workshop) not in email.body
        assert str(other_order) not in email.body


# --- Los triggers de F5 con los tres roles ------------------------------------------


async def in_status(workshop_id: UUID, client_id: UUID, status: str) -> UUID:
    """Un aviso llevado a `status` por los caminos de la aplicación."""
    if status == "pending":
        return await create(workshop_id, client_id)
    if status == "skipped":
        notification_id = await create(workshop_id, client_id)
        await notification_service.dispatch(
            workshop_id, InMemoryJobQueue(), email_enabled=False
        )
        return notification_id
    notification_id, attempt = await claimed(workshop_id, client_id)
    if status == "claimed":
        return notification_id
    composers: Any = FAKE_COMPOSERS
    sender: Any = InMemoryEmailSender()
    if status == "unknown":
        sender = FailingSender(EmailDeliveryUnknownError("corte en DATA"))
    elif status == "failed":
        sender = FailingSender(EmailNotSentError("550 rechazado", smtp_code=550))
    elif status == "cancelled":

        async def obsolete(*_: Any) -> NotDelivered:
            return NotDelivered(NotificationStatus.CANCELLED, FailureReason.OBSOLETE)

        composers = {KIND: obsolete}
    else:
        assert status == "sent"
    assert (
        await notification_service.deliver(
            workshop_id, notification_id, attempt, sender, composers
        )
        == status
    )
    return notification_id


# Cada sentencia cumple todos los CHECK del estado al que va: lo único que la
# para es el trigger (si no, la prueba pasaría sin él).
REOPEN = {
    "pending": (
        "UPDATE notifications SET status = 'pending', claimed_at = NULL,"
        " sent_at = NULL, failure_reason = NULL, next_attempt_at = NULL,"
        " smtp_code = NULL WHERE id = :n"
    ),
    "claimed": (
        "UPDATE notifications SET status = 'claimed', attempts = attempts + 1,"
        " claimed_at = clock_timestamp(), sent_at = NULL, failure_reason = NULL,"
        " next_attempt_at = NULL, smtp_code = NULL WHERE id = :n"
    ),
    "failed": (
        "UPDATE notifications SET status = 'failed', claimed_at = NULL,"
        " sent_at = NULL, failure_reason = 'not_sent',"
        " next_attempt_at = clock_timestamp(), smtp_code = NULL WHERE id = :n"
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("target", sorted(REOPEN))
@pytest.mark.parametrize("final", ["sent", "unknown", "cancelled", "skipped"])
async def test_no_role_reopens_a_final_notice(
    engines: Engines,
    two_workshops: TwoWorkshops,
    client_a: UUID,
    final: str,
    target: str,
    role: str,
) -> None:
    """RF-62: lo que pudo salir (`sent`, `unknown`) no se reintenta, y lo que se
    decidió no enviar (`cancelled`, `skipped`) no vuelve a la cola, ni por SQL
    con ninguno de los tres roles (axtton_app tiene permiso sobre esas columnas:
    lo para el trigger, no el permiso)."""
    a = two_workshops.a
    notification_id = await in_status(a, client_a, final)
    before = await row(engines, notification_id)
    async with getattr(engines, role).connect() as conn:
        await set_workshops(conn, a)
        with pytest.raises(DBAPIError, match=f"cannot go from {final} to {target}"):
            await conn.execute(text(REOPEN[target]), {"n": notification_id})
        await conn.rollback()
    assert await row(engines, notification_id) == before


# Lo que el taller ve de un aviso terminado (RF-69): con el estado igual, nada
# más cambia. Cada sentencia cumple los CHECK; solo la para el trigger
# `notifications_final_frozen` (0023noticefinal, lo encontró este cierre).
REWRITE = {
    "sent": [
        "UPDATE notifications SET sent_at = sent_at - interval '3 days' WHERE id = :n",
        "UPDATE notifications SET smtp_code = 250 WHERE id = :n",
    ],
    **{
        final: [
            "UPDATE notifications SET failure_reason = 'compose_failed' WHERE id = :n",
            "UPDATE notifications SET smtp_code = 421 WHERE id = :n",
        ]
        for final in ("unknown", "cancelled", "skipped")
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(
    ("final", "statement"),
    [(final, sql) for final, sqls in REWRITE.items() for sql in sqls],
)
async def test_a_finished_notice_keeps_its_record(
    engines: Engines,
    two_workshops: TwoWorkshops,
    client_a: UUID,
    final: str,
    statement: str,
    role: str,
) -> None:
    """Ni la hora de envío, ni el motivo, ni el código del servidor de un aviso
    terminado se reescriben, con ninguno de los tres roles: es el historial que
    ve el taller (RF-69)."""
    a = two_workshops.a
    notification_id = await in_status(a, client_a, final)
    before = await row(engines, notification_id)
    async with getattr(engines, role).connect() as conn:
        await set_workshops(conn, a)
        with pytest.raises(DBAPIError, match=f"is {final} and cannot change"):
            await conn.execute(text(statement), {"n": notification_id})
        await conn.rollback()
    assert await row(engines, notification_id) == before


IDENTITY = {
    "id": "gen_random_uuid()",
    "workshop_id": "gen_random_uuid()",
    "kind": "'vehicle_ready'",
    "dedupe_key": "'otro-motivo'",
    "client_id": "gen_random_uuid()",
    "work_order_id": "gen_random_uuid()",
    "quote_id": "gen_random_uuid()",
    "created_at": "created_at - interval '1 hour'",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("column", sorted(IDENTITY))
async def test_what_a_notice_is_about_never_changes(
    engines: Engines,
    two_workshops: TwoWorkshops,
    client_a: UUID,
    column: str,
    role: str,
) -> None:
    """De qué y para quién es un aviso no cambia: sin eso, se podría reenviar un
    motivo ya avisado cambiándole la clave, o mandarlo a otro cliente. A
    axtton_app ni siquiera le dan permiso; a los otros dos, el trigger los para
    antes que cualquier FK o RLS."""
    a = two_workshops.a
    notification_id = await create(a, client_a)
    expected = (
        "permission denied" if role == "app" else "cannot change what it is about"
    )
    async with getattr(engines, role).connect() as conn:
        await set_workshops(conn, a)
        with pytest.raises(DBAPIError, match=expected):
            await conn.execute(
                text(
                    f"UPDATE notifications SET {column} = {IDENTITY[column]}"
                    " WHERE id = :n"
                ),
                {"n": notification_id},
            )
        await conn.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("status", ["pending", "failed"])
async def test_no_role_deletes_a_notice_not_even_one_that_never_went_out(
    engines: Engines,
    two_workshops: TwoWorkshops,
    client_a: UUID,
    status: str,
    role: str,
) -> None:
    """La fila es lo que impide avisar dos veces del mismo motivo: borrar una
    pendiente dejaría crearla otra vez. También un DELETE sin WHERE."""
    a = two_workshops.a
    await in_status(a, client_a, status)
    expected = "permission denied" if role == "app" else "cannot be deleted"
    async with getattr(engines, role).connect() as conn:
        await set_workshops(conn, a)
        with pytest.raises(DBAPIError, match=expected):
            await conn.execute(text("DELETE FROM notifications"))
        await conn.rollback()
    assert await scalar(engines, "SELECT count(*) FROM notifications") == 1


# (estado de partida, sentencia, error del trigger)
ATTEMPT_TAMPERING = [
    (
        "pending",
        (
            "UPDATE notifications SET status = 'claimed', attempts = attempts + 2,"
            " claimed_at = clock_timestamp() WHERE id = :n"
        ),
        "wrong attempts",
    ),
    (
        "pending",
        "UPDATE notifications SET attempts = attempts + 1 WHERE id = :n",
        "attempts change only with its status",
    ),
    (
        # Mover el reclamo sin cambiar de estado lo escondería del barrido de
        # abandonados (B6).
        "claimed",
        (
            "UPDATE notifications SET claimed_at = clock_timestamp() + interval '1 day'"
            " WHERE id = :n"
        ),
        "attempts change only with its status",
    ),
    (
        "failed",
        (
            "UPDATE notifications SET status = 'claimed', claimed_at = clock_timestamp(),"
            " failure_reason = NULL, next_attempt_at = NULL, smtp_code = NULL"
            " WHERE id = :n"
        ),
        "wrong attempts",
    ),
    (
        "claimed",
        (
            "UPDATE notifications SET status = 'sent', sent_at = clock_timestamp(),"
            " claimed_at = NULL, attempts = attempts - 1 WHERE id = :n"
        ),
        "wrong attempts",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(
    ("status", "statement", "expected"),
    ATTEMPT_TAMPERING,
    ids=["claim+2", "attempts-alone", "claimed_at-alone", "retry+0", "sent-1"],
)
async def test_the_attempt_count_cannot_be_bent_by_any_role(
    engines: Engines,
    two_workshops: TwoWorkshops,
    client_a: UUID,
    status: str,
    statement: str,
    expected: str,
    role: str,
) -> None:
    """Cada reclamo es exactamente un intento más (B5): un reintento que no
    sumara, o unos intentos rebajados, dejarían reintentar sin fin."""
    a = two_workshops.a
    notification_id = await in_status(a, client_a, status)
    async with getattr(engines, role).connect() as conn:
        await set_workshops(conn, a)
        with pytest.raises(DBAPIError, match=expected):
            await conn.execute(text(statement), {"n": notification_id})
        await conn.rollback()


@pytest.mark.asyncio
async def test_the_platform_cannot_mark_a_valid_version_expired_either(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """`quotes_expire_only_when_overdue` con el tercer rol (test_quote_expiry.py
    prueba la aplicación y el dueño): la plataforma se salta RLS, no el
    trigger."""
    _, _, quote_id, _ = await sent_quote(engines, two_workshops, make_account)
    async with engines.platform.connect() as conn:
        with pytest.raises(DBAPIError, match="is still valid until"):
            await conn.execute(
                text("UPDATE quotes SET status = 'expired' WHERE id = :q"),
                {"q": quote_id},
            )
        await conn.rollback()
    assert (
        await scalar(engines, "SELECT status FROM quotes WHERE id = :q", q=quote_id)
        == "sent"
    )


# --- Carreras -----------------------------------------------------------------------


@pytest_asyncio.fixture
async def maria_with_email(engines: Engines, shop: Shop) -> Shop:
    await set_client(engines, shop, email="maria@example.com")
    return shop


@pytest.mark.asyncio
async def test_a_dispatch_during_an_undo_does_not_claim_the_notice_being_cancelled(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    """Dos transacciones reales: el taller deshace "lista" (el aviso pendiente ya
    está cancelado, sin confirmar) mientras pasa el despachador. El reclamo se
    salta la fila bloqueada; sin `FOR UPDATE` en la búsqueda, la reclamaría al
    soltarse y chocaría con el trigger (cancelled → claimed)."""
    shop = maria_with_email
    order = await ready_order(client, shop)
    order_id = UUID(order["id"])
    a = await workshop_of(engines, order["id"])
    seq = await last_seq(engines, order["id"])
    employee_id, user_id = await admin_of(engines, a)
    version = (await get(client, shop.headers, order["id"]))["version"]
    queue = InMemoryJobQueue()

    async with open_transaction(a) as session:
        await order_service.undo_last_change(
            session, a, user_id, employee_id, order_id, expected_version=version
        )
        await session.flush()
        work = asyncio.create_task(
            notification_service.dispatch(a, queue, email_enabled=True)
        )
        await asyncio.sleep(GRACE)
        await session.commit()
    assert await asyncio.wait_for(work, timeout=10) == 0
    assert queue.jobs == []
    assert (await notices(engines))[ready_key(order_id, seq)]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_an_undo_does_not_wait_for_a_ready_email_in_flight(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    """El correo de "lista" está hablando con el SMTP (la fila bloqueada hasta 60
    s) cuando el taller deshace: deshacer no espera a esa fila, porque solo
    cancela lo que no ha salido (`pending`, `failed`). Lo que ya está en vuelo
    sale: no se puede deshacer un correo (arquitectura §8)."""
    shop = maria_with_email
    order = await ready_order(client, shop)
    a = await workshop_of(engines, order["id"])
    [(notification_id, attempt)] = await jobs_of_one_pass(a)
    slow = SlowSender()
    sending = asyncio.create_task(
        notification_service.deliver(a, notification_id, attempt, slow, COMPOSERS)
    )
    await asyncio.wait_for(slow.started.wait(), timeout=5)

    undoing = asyncio.create_task(undo(client, shop.headers, order["id"]))
    await asyncio.sleep(GRACE)
    undone_while_sending = undoing.done()
    slow.release.set()
    response, sent = await asyncio.wait_for(
        asyncio.gather(undoing, sending), timeout=10
    )

    assert undone_while_sending, "deshacer esperó a que terminara el envío"
    assert response.status_code == 204, response.text
    assert sent == NotificationStatus.SENT and len(slow.sent) == 1
    assert (await get(client, shop.headers, order["id"]))["status"] != "ready"


@pytest.mark.asyncio
async def test_cancelling_while_the_quote_email_is_in_flight_still_tells_the_client(
    client: AsyncClient, maria_with_email: Shop, engines: Engines
) -> None:
    """Especificación §6: se avisa de la anulación "si ya lo había recibido". Aquí
    el correo de la versión está en vuelo (reclamado, compuesto con la versión
    aún enviada, hablando con el SMTP) cuando el taller la anula y el
    despachador reclama el aviso de anulación. El de envío acaba saliendo, así
    que el cliente tiene que recibir también el de anulación."""
    shop = maria_with_email
    order_id, quote_id = await sent_order(client, shop)
    a = await workshop_of(engines, order_id)
    [(sent_notice, sent_attempt)] = await jobs_of_one_pass(a)
    slow = SlowSender()
    sending = asyncio.create_task(
        notification_service.deliver(a, sent_notice, sent_attempt, slow, COMPOSERS)
    )
    await asyncio.wait_for(slow.started.wait(), timeout=5)

    assert (await cancel(client, shop, order_id, quote_id)).status_code == 204
    cancelled_notice = await notice_id(engines, a, f"quote_cancelled:{quote_id}")
    [(claimed_id, attempt)] = await jobs_of_one_pass(a)
    assert claimed_id == cancelled_notice
    outbox = InMemoryEmailSender()
    telling = asyncio.create_task(
        notification_service.deliver(a, cancelled_notice, attempt, outbox, COMPOSERS)
    )
    await asyncio.sleep(GRACE)
    slow.release.set()
    await asyncio.wait_for(asyncio.gather(sending, telling), timeout=10)
    assert len(slow.sent) == 1  # el de envío salió

    # Si la anulación quedó para un reintento, se le deja llegar.
    for _ in range(2):
        found = await row(engines, cancelled_notice)
        if found["status"] != "failed" or found["next_attempt_at"] is None:
            break
        await age(engines, cancelled_notice, "next_attempt_at", "1 hour")
        for retry_id, retry_attempt in await jobs_of_one_pass(a):
            await notification_service.deliver(
                a, retry_id, retry_attempt, outbox, COMPOSERS
            )
    assert await status_of_notice(engines, cancelled_notice) == "sent"
    assert len(outbox.sent) == 1


async def make_valid_for(quote_id: UUID, seconds: float) -> None:
    """Deja a la versión enviada `seconds` de validez. El dueño apaga en su
    transacción el trigger que congela lo enviado (como `expire_by_sql`)."""
    platform = create_async_engine(os.environ["PLATFORM_DATABASE_URL"])
    owner = create_async_engine(os.environ["MIGRATIONS_DATABASE_URL"])
    try:
        async with platform.connect() as conn:
            workshop = await conn.scalar(
                text("SELECT workshop_id FROM quotes WHERE id = :q"), {"q": quote_id}
            )
        async with owner.begin() as conn:
            await set_workshops(conn, workshop)
            await conn.execute(
                text("ALTER TABLE quotes DISABLE TRIGGER quotes_frozen_after_send")
            )
            await conn.execute(
                text(
                    "UPDATE quotes SET valid_until = clock_timestamp()"
                    " + make_interval(secs => :s) WHERE id = :q"
                ),
                {"q": quote_id, "s": seconds},
            )
            await conn.execute(
                text("ALTER TABLE quotes ENABLE TRIGGER quotes_frozen_after_send")
            )
    finally:
        await platform.dispose()
        await owner.dispose()


async def wait_until_overdue(engines: Engines, quote_id: UUID) -> None:
    for _ in range(100):
        if await scalar(
            engines,
            "SELECT valid_until <= clock_timestamp() FROM quotes WHERE id = :q",
            q=quote_id,
        ):
            return
        await asyncio.sleep(0.1)
    raise AssertionError("la versión no llegó a caducar")


@pytest.mark.asyncio
async def test_a_decision_taken_in_time_wins_over_the_expiry_that_waits_for_it(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """Dos transacciones reales: el taller registra la aprobación un instante
    antes de que acabe la validez y aún no ha confirmado cuando el worker pasa.
    El worker ve la versión enviada y fuera de plazo, espera a su bloqueo y, al
    soltarse, la encuentra aprobada: no la toca (ni un 500 por el trigger)."""
    order, staff, quote_id, version = await sent_quote(
        engines, two_workshops, make_account
    )
    a = order.workshop_id
    await make_valid_for(quote_id, 2)

    async with open_transaction(a) as session:
        await quote_service.record_decision(
            session,
            a,
            staff.user_id,
            staff.employee_id,
            quote_id,
            expected_version=version,
            outcome=Outcome.APPROVED,
            channel=DecisionChannel.PHONE,
            note=None,
        )
        await wait_until_overdue(engines, quote_id)
        work = asyncio.create_task(quote_service.expire_overdue(a))
        await asyncio.sleep(GRACE)
        waited = not work.done()
        await session.commit()
    expired = await asyncio.wait_for(work, timeout=10)

    assert waited, "el worker no llegó a esperar a la decisión: no hubo carrera"
    assert expired == 0
    assert (
        await scalar(engines, "SELECT status FROM quotes WHERE id = :q", q=quote_id)
        == QuoteStatus.APPROVED
    )


@pytest.mark.asyncio
async def test_a_cancellation_in_progress_wins_over_the_expiry_that_waits_for_it(
    engines: Engines, two_workshops: TwoWorkshops, make_account: MakeAccount
) -> None:
    """El taller anula una versión ya fuera de plazo (aún sin marcar) mientras
    el worker la iba a marcar: el worker espera y la deja anulada."""
    order, staff, quote_id, version = await sent_quote(
        engines, two_workshops, make_account
    )
    a = order.workshop_id
    await expire_by_sql(str(quote_id))

    async with open_transaction(a) as session:
        await quote_service.cancel_quote(
            session,
            a,
            staff.user_id,
            staff.employee_id,
            quote_id,
            expected_version=version,
            reason="Precio equivocado",
        )
        work = asyncio.create_task(quote_service.expire_overdue(a))
        await asyncio.sleep(GRACE)
        waited = not work.done()
        await session.commit()
    expired = await asyncio.wait_for(work, timeout=10)

    assert waited, "el worker no llegó a esperar a la anulación: no hubo carrera"
    assert expired == 0
    assert (
        await scalar(engines, "SELECT status FROM quotes WHERE id = :q", q=quote_id)
        == QuoteStatus.CANCELLED
    )


# --- El enlace del portal por el worker ----------------------------------------------


@pytest.mark.asyncio
async def test_what_is_enqueued_for_a_link_is_the_same_whoever_asks(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    queue: InMemoryJobQueue,
) -> None:
    """RF-41 en lo encolado, no solo en la respuesta: el mismo trabajo, con las
    mismas opciones y los mismos argumentos (taller y email, sin token ni
    cliente), sea el email de un cliente, de nadie, de un archivado o de otro
    taller, o el taller inexistente. Y la API no emite ningún enlace."""
    known, archived, of_b = new_email(), new_email(), new_email()
    await add_client(engines, two_workshops.a, known)
    archived_id = await add_client(engines, two_workshops.a, archived)
    await add_client(engines, two_workshops.b, of_b)
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE clients SET archived_at = clock_timestamp() WHERE id = :c"),
            {"c": archived_id},
        )
    nobody = new_email()
    asked = [
        (two_workshops.a, known),
        (two_workshops.a, nobody),
        (two_workshops.a, archived),
        (two_workshops.a, of_b),
        (UUID(int=7), known),
    ]
    for workshop_id, email in asked:
        assert await request_link_status(client, workshop_id, email) == 202

    assert len(queue.jobs) == len(asked)
    for job, (workshop_id, email) in zip(queue.jobs, asked, strict=True):
        assert job.kwargs == {"workshop_id": str(workshop_id), "email": email}
        assert job.key is None
    # Fuera de sus argumentos, los cinco trabajos son idénticos.
    options = {
        (
            job.job,
            job.timeout_seconds,
            job.max_attempts,
            job.retry_delay_seconds,
            job.keep_seconds,
        )
        for job in queue.jobs
    }
    assert len(options) == 1
    assert await scalar(engines, "SELECT count(*) FROM portal_links") == 0


@pytest.mark.asyncio
async def test_the_error_saq_keeps_for_a_refused_link_does_not_carry_the_email(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    """SAQ guarda con el trabajo `traceback.format_exc()` del error. El servidor
    que rechaza suele repetir la dirección (550 <email>…): ni el mensaje, ni la
    causa, ni el contexto encadenado pueden llevarla (RNF-40). Mirar solo
    `__cause__` no basta: sin `from None`, el error original iría en el
    traceback como "During handling of the above exception"."""
    email = new_email()
    await add_client(engines, two_workshops.a, email)
    context = cast(WorkerContext, {"email_sender": Refusing()})
    with pytest.raises(LinkNotSentError) as refused:
        await send_portal_link(context, workshop_id=str(two_workshops.a), email=email)
    stored = "".join(traceback.format_exception(refused.value))
    assert email not in stored
    assert email.split("@")[0] not in stored


# --- RNF-40 en la bandeja -------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_outbox_keeps_neither_the_email_nor_the_text_of_what_went_out(
    client: AsyncClient, shop: Shop, engines: Engines
) -> None:
    """La fila del aviso solo lleva ids y códigos: ni el email del cliente, ni su
    nombre, ni el asunto o el texto del correo, ni el texto con el que el
    servidor rechazó uno (que suele repetir la dirección). Tampoco la ruta que
    los enseña al taller."""
    email, name = "eulalia.pardo@example.com", "Eulalia Pardo Quintana"
    await set_client(engines, shop, email=email, name=name)
    order_id, quote_id = await sent_order(client, shop)
    a = await workshop_of(engines, order_id)
    [sent] = (await deliver_due(a)).sent
    # La anulación sí sale (el de envío salió), pero el servidor la rechaza con
    # un texto que lleva la dirección.
    assert (await cancel(client, shop, order_id, quote_id)).status_code == 204
    [(cancelled_notice, attempt)] = await jobs_of_one_pass(a)
    assert (
        await notification_service.deliver(
            a, cancelled_notice, attempt, Refusing(), COMPOSERS
        )
        == NotificationStatus.FAILED
    )
    assert (await row(engines, cancelled_notice))["smtp_code"] == 550

    async with engines.platform.connect() as conn:
        stored = "\n".join(
            (await conn.scalars(text("SELECT n::text FROM notifications n"))).all()
        ).lower()
    shown = (
        await client.get(
            f"/api/v1/workshop/orders/{order_id}/notifications", headers=shop.headers
        )
    ).text.lower()
    assert len(await notices_of(client, shop.headers, order_id)) == 2
    body_lines = [line for line in sent.body.splitlines() if len(line.strip()) > 15]
    searched = [email, email.split("@")[0], name, "eulalia", sent.subject]
    for place in (stored, shown):
        assert [value for value in searched if value.lower() in place] == []
        assert [line for line in body_lines if line.strip().lower() in place] == []


@pytest.mark.asyncio
async def test_anonymizing_a_client_with_notices_leaves_nothing_of_them_anywhere(
    client: AsyncClient, shop: Shop, engines: Engines
) -> None:
    """El barrido de test_anonymize.py, con un cliente al que ya se avisó (un
    "lista" enviado y otro intento rechazado por el servidor con su dirección)
    antes de anonimizarlo: ni la bandeja ni nada de lo que dejó el envío guarda
    lo que era."""
    maria, _ = await maria_with_history(client, shop)
    order = await ready_order(client, shop)
    a = await workshop_of(engines, order["id"])
    [(ready_notice, attempt)] = await jobs_of_one_pass(a)
    assert (
        await notification_service.deliver(
            a, ready_notice, attempt, Refusing(), COMPOSERS
        )
        == NotificationStatus.FAILED
    )
    await age(engines, ready_notice, "next_attempt_at", "1 hour")
    [(retry, retry_attempt)] = await jobs_of_one_pass(a)
    outbox = InMemoryEmailSender()
    assert (
        await notification_service.deliver(a, retry, retry_attempt, outbox, COMPOSERS)
        == NotificationStatus.SENT
    )
    assert outbox.sent[0].to == PERSONAL["email"]
    await deliver_order(order["id"])

    maria = await read_client(client, shop.headers, maria["id"])
    assert (await anonymize(client, shop.headers, maria)).status_code == 204

    dump = await dump_of_every_table()
    assert [value for value in PERSONAL.values() if value.lower() in dump] == []
    assert "maria sanchez" not in dump


# --- Lo que queda en los registros (RNF-40) -------------------------------------------


def test_a_failing_job_is_logged_without_its_arguments(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SAQ registra un trabajo que falla con `logger.exception("Error processing
    job %s", job)`, y el `repr` de un trabajo lleva sus argumentos: el del enlace
    del portal, el email. El worker filtra el registro de SAQ (lo encontró este
    cierre)."""
    from saq import Job

    import app.worker  # noqa: F401 (pone el filtro)

    email = new_email()
    job = Job(
        "send_portal_link", kwargs={"workshop_id": "w", "email": email}, retries=3
    )
    assert email in repr(job)
    with caplog.at_level("ERROR", logger="saq"):
        try:
            raise LinkNotSentError(550)
        except LinkNotSentError:
            logging.getLogger("saq").exception("Error processing job %s", job)
    assert "send_portal_link" in caplog.text
    assert email not in caplog.text


@pytest.mark.asyncio
async def test_an_unclassified_error_sending_a_link_is_not_retried_nor_logged(
    engines: Engines,
    two_workshops: TwoWorkshops,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un error sin clasificar al enviar el enlace puede haber salido, como en la
    bandeja (B4): no se reintenta (saldría otro correo con otro enlace), no se
    revoca (si llegó, que sirva) y al registro solo va su tipo, nunca su texto."""
    email = new_email()
    await add_client(engines, two_workshops.a, email)

    class Broken(InMemoryEmailSender):
        async def send(self, message: Any) -> None:
            raise RuntimeError(f"socket roto hablando con {message.to}")

    from app.services import portal_auth as portal_auth_service
    from app.services.portal_auth import LinkSendOutcome

    with caplog.at_level("WARNING"):
        outcome = await portal_auth_service.send_link(two_workshops.a, email, Broken())
    assert outcome == LinkSendOutcome.DELIVERY_UNKNOWN
    assert "RuntimeError" in caplog.text
    assert email not in caplog.text
    revoked = await scalar(
        engines,
        "SELECT count(*) FROM portal_links l JOIN clients c ON c.id = l.client_id"
        " WHERE c.email = :e AND l.revoked_at IS NULL AND l.used_at IS NULL",
        e=email,
    )
    assert revoked == 1


@pytest.mark.asyncio
async def test_a_refused_notice_is_logged_without_the_server_text(
    two_workshops: TwoWorkshops,
    client_a: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """El servidor que rechaza repite la dirección (550 <email>…): el registro de
    la bandeja lleva el código, no el texto."""
    with caplog.at_level("WARNING"):
        await in_status(two_workshops.a, client_a, "failed")
        await in_status(two_workshops.a, client_a, "unknown")
    assert "550" in caplog.text
    assert "rechazado" not in caplog.text and "corte en DATA" not in caplog.text
