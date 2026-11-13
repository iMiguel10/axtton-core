"""La bandeja de avisos (F5 paso 4, arquitectura §8): "nunca dos veces" (RF-62).

B1–B6 adaptadas de Applications Tracker. Las carreras van con dos transacciones
reales (CLAUDE.md §8: `asyncio.gather` sobre la API no las prueba), y el doble
envío, con un emisor de correo que se queda esperando a mitad del envío.
"""

import asyncio
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import workshop_transaction
from app.domain.notifications import (
    MAX_ATTEMPTS,
    FailureReason,
    NotificationKind,
    NotificationStatus,
)
from app.infra.email import (
    Email,
    EmailDeliveryUnknownError,
    EmailNotSentError,
    InMemoryEmailSender,
)
from app.infra.queue import InMemoryJobQueue
from app.jobs.context import WorkerContext
from app.jobs.notifications import send_notification
from app.models import Notification
from app.platform.scheduler import (
    workshops_with_abandoned_notifications,
    workshops_with_due_notifications,
)
from app.repositories import notifications as notification_repo
from app.services import notifications as service
from app.services.notifications import NotDelivered
from tests.conftest import Engines, TwoWorkshops
from tests.test_concurrency import (
    GRACE,
    dispose_global_engines,  # noqa: F401 (autouse)
    finish,
    open_transaction,
)
from tests.test_portal_auth import add_client
from tests.test_rls import set_workshops

KIND = NotificationKind.QUOTE_SENT


async def compose_ok(session: AsyncSession, notification: Notification) -> Email:
    return Email(to="ana@example.com", subject="Tu presupuesto", body="Texto")


COMPOSERS = {KIND: compose_ok}


class FailingSender:
    enabled = True

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    async def send(self, email: Email) -> None:
        self.calls += 1
        raise self.error


class SlowSender:
    """Se queda a mitad del envío hasta que la prueba lo suelta."""

    enabled = True

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.sent: list[Email] = []

    async def send(self, email: Email) -> None:
        self.started.set()
        await self.release.wait()
        self.sent.append(email)


@pytest_asyncio.fixture
async def client_a(engines: Engines, two_workshops: TwoWorkshops) -> UUID:
    return await add_client(engines, two_workshops.a, "ana@example.com")


async def create(workshop_id: UUID, client_id: UUID, key: str | None = None) -> UUID:
    dedupe_key = key or f"quote_sent:{uuid4()}"
    async with workshop_transaction([workshop_id]) as session:
        assert await service.create(
            session,
            workshop_id=workshop_id,
            kind=KIND,
            dedupe_key=dedupe_key,
            client_id=client_id,
        )
        found = await session.scalar(
            text("SELECT id FROM notifications WHERE dedupe_key = :k"),
            {"k": dedupe_key},
        )
    assert isinstance(found, UUID)
    return found


async def claimed(workshop_id: UUID, client_id: UUID) -> tuple[UUID, int]:
    """Un aviso creado y reclamado por el despachador; devuelve id e intento."""
    notification_id = await create(workshop_id, client_id)
    queue = InMemoryJobQueue()
    assert await service.dispatch(workshop_id, queue, email_enabled=True) == 1
    [job] = queue.jobs
    assert job.kwargs["notification_id"] == str(notification_id)
    return notification_id, int(cast(int, job.kwargs["attempt"]))


async def row(engines: Engines, notification_id: UUID) -> dict[str, Any]:
    async with engines.platform.connect() as conn:
        found = (
            (
                await conn.execute(
                    text("SELECT * FROM notifications WHERE id = :n"),
                    {"n": notification_id},
                )
            )
            .mappings()
            .one()
        )
    return dict(found)


async def age(engines: Engines, notification_id: UUID, column: str, by: str) -> None:
    """Mueve hacia atrás una hora del aviso. El dueño apaga el trigger dentro de
    su transacción (como la demo para mover fechas): el trigger no deja mover el
    reclamo sin cambiar de estado."""
    async with engines.owner.begin() as conn:
        await conn.execute(
            text("ALTER TABLE notifications NO FORCE ROW LEVEL SECURITY")
        )
        await conn.execute(
            text("ALTER TABLE notifications DISABLE TRIGGER notifications_transitions")
        )
        await conn.execute(
            text(
                f"UPDATE notifications SET {column} = {column} - interval '{by}'"
                " WHERE id = :n"
            ),
            {"n": notification_id},
        )
        await conn.execute(
            text("ALTER TABLE notifications ENABLE TRIGGER notifications_transitions")
        )
        await conn.execute(text("ALTER TABLE notifications FORCE ROW LEVEL SECURITY"))


# --- Crear: el mismo motivo es la misma fila --------------------------------------


@pytest.mark.asyncio
async def test_the_same_reason_creates_a_single_notification(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    a = two_workshops.a
    await create(a, client_a, "quote_sent:uno")
    async with workshop_transaction([a]) as session:
        again = await service.create(
            session,
            workshop_id=a,
            kind=KIND,
            dedupe_key="quote_sent:uno",
            client_id=client_a,
        )
    assert again is False
    async with engines.platform.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM notifications")) == 1


@pytest.mark.asyncio
async def test_two_changes_at_once_create_one_notification(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    """Dos transacciones reales crean el mismo motivo: la segunda espera al índice
    único y, al confirmar la primera, no inserta nada (y no da un 500)."""
    a = two_workshops.a
    values: dict[str, Any] = {
        "workshop_id": a,
        "kind": KIND,
        "dedupe_key": "quote_sent:carrera",
        "client_id": client_a,
    }
    async with open_transaction(a) as first, open_transaction(a) as second:
        assert await service.create(first, **values) is True
        work = asyncio.create_task(service.create(second, **values))
        await asyncio.sleep(GRACE)
        assert not work.done()  # esperando al índice único
        await first.commit()
        assert await finish(second, work) is False


@pytest.mark.asyncio
async def test_a_notification_dies_with_the_change_that_caused_it(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    """Invariante 8: en la transacción del cambio. Si se deshace, no queda aviso."""
    a = two_workshops.a
    async with open_transaction(a) as session:
        await service.create(
            session, workshop_id=a, kind=KIND, dedupe_key="x:1", client_id=client_a
        )
        await session.rollback()
    async with engines.platform.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM notifications")) == 0


# --- El despachador ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_dispatcher_claims_and_enqueues_one_send_per_attempt(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    notification_id = await create(two_workshops.a, client_a)
    queue = InMemoryJobQueue()
    assert await service.dispatch(two_workshops.a, queue, email_enabled=True) == 1

    [job] = queue.jobs
    assert job.job == "send_notification"
    # Un solo intento en la cola: el reintento lo decide el estado del aviso.
    assert (job.max_attempts, job.timeout_seconds) == (1, 60)
    found = await row(engines, notification_id)
    # La clave lleva la hora del reclamo: única en cada reclamo.
    assert job.key == (
        f"notification:{notification_id}:{found['claimed_at'].timestamp():.6f}"
    )
    assert job.kwargs == {
        "workshop_id": str(two_workshops.a),
        "notification_id": str(notification_id),
        "attempt": 1,
    }
    assert (found["status"], found["attempts"]) == ("claimed", 1)
    assert found["claimed_at"] is not None
    # Una segunda pasada no lo vuelve a reclamar.
    assert await service.dispatch(two_workshops.a, queue, email_enabled=True) == 0


@pytest.mark.asyncio
async def test_b3_two_dispatchers_at_once_claim_each_notification_once(
    two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    """Dos transacciones reales: la primera reclama y no confirma; la segunda no
    puede reclamar lo mismo (se salta las filas bloqueadas). Sin el bloqueo, la
    segunda esperaría a la fila y la reclamaría otra vez, con otro intento."""
    a = two_workshops.a
    first_id = await create(a, client_a)
    async with open_transaction(a) as first, open_transaction(a) as second:
        claimed_first = await notification_repo.claim_due(first, 10)
        assert [n for n, _, _ in claimed_first] == [first_id]
        work = asyncio.create_task(notification_repo.claim_due(second, 10))
        await asyncio.sleep(GRACE)
        await first.commit()
        assert await finish(second, work) == []


@pytest.mark.asyncio
async def test_when_the_queue_is_down_the_claim_is_undone(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    """Valkey caído: el aviso vuelve a esperar, con el intento devuelto, en vez de
    quedarse reclamado hasta darse por perdido."""
    notification_id = await create(two_workshops.a, client_a)
    down = InMemoryJobQueue(fail=True)
    assert await service.dispatch(two_workshops.a, down, email_enabled=True) == 0
    found = await row(engines, notification_id)
    assert (found["status"], found["attempts"], found["claimed_at"]) == (
        "pending",
        0,
        None,
    )
    # Y la pasada siguiente, con la cola de vuelta, lo envía.
    queue = InMemoryJobQueue()
    assert await service.dispatch(two_workshops.a, queue, email_enabled=True) == 1
    assert queue.jobs[0].kwargs["attempt"] == 1


@pytest.mark.asyncio
async def test_a_job_left_behind_by_an_undone_claim_sends_at_most_once(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    """Encolar falló, pero el trabajo llegó a la cola (se perdió la respuesta): el
    reclamo se deshizo y el siguiente repite el número de intento. Su clave es
    otra, así que SAQ no lo descarta, y entre los dos trabajos sale un correo."""
    a = two_workshops.a
    notification_id = await create(a, client_a)
    lost = InMemoryJobQueue()
    await service.dispatch(a, lost, email_enabled=True)
    [old_job] = lost.jobs
    async with workshop_transaction([a]) as session:
        assert await notification_repo.unclaim(
            session, notification_id, cast(int, old_job.kwargs["attempt"])
        )
    queue = InMemoryJobQueue()
    await service.dispatch(a, queue, email_enabled=True)
    [new_job] = queue.jobs
    assert new_job.kwargs["attempt"] == old_job.kwargs["attempt"]
    assert new_job.key != old_job.key

    outbox = InMemoryEmailSender()
    results = [
        await service.deliver(
            a, notification_id, cast(int, job.kwargs["attempt"]), outbox, COMPOSERS
        )
        for job in (old_job, new_job)
    ]
    assert results == [NotificationStatus.SENT, None]
    assert len(outbox.sent) == 1


@pytest.mark.asyncio
async def test_a_job_from_an_earlier_attempt_does_nothing(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    """Un trabajo del primer intento que SAQ relanza tarde, cuando el aviso ya va
    por el segundo: no lo envía él; lo envía el trabajo de su intento."""
    a = two_workshops.a
    notification_id, first = await claimed(a, client_a)
    failing = FailingSender(EmailNotSentError("421 ocupado", smtp_code=421))
    await service.deliver(a, notification_id, first, failing, COMPOSERS)
    await age(engines, notification_id, "next_attempt_at", "1 hour")
    queue = InMemoryJobQueue()
    await service.dispatch(a, queue, email_enabled=True)
    second = cast(int, queue.jobs[0].kwargs["attempt"])
    assert second == first + 1

    outbox = InMemoryEmailSender()
    assert await service.deliver(a, notification_id, first, outbox, COMPOSERS) is None
    assert outbox.sent == []
    assert await service.deliver(a, notification_id, second, outbox, COMPOSERS) == (
        NotificationStatus.SENT
    )


@pytest.mark.asyncio
async def test_without_smtp_due_notifications_are_skipped_with_the_reason(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    """RNF-32: la demo no tiene correo. El taller ve que no se avisó y por qué."""
    notification_id = await create(two_workshops.a, client_a)
    queue = InMemoryJobQueue()
    assert await service.dispatch(two_workshops.a, queue, email_enabled=False) == 1
    assert queue.jobs == []
    found = await row(engines, notification_id)
    assert (found["status"], found["failure_reason"]) == ("skipped", "email_disabled")


@pytest.mark.asyncio
async def test_the_worker_dispatches_and_sends_end_to_end(
    engines: Engines,
    two_workshops: TwoWorkshops,
    client_a: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Del despachador (planificador incluido) al trabajo de envío."""
    from app.jobs.notifications import dispatch_notifications
    from app.services import notice_composers

    notification_id = await create(two_workshops.a, client_a)
    outbox = InMemoryEmailSender()
    queue = InMemoryJobQueue()
    ctx = cast(WorkerContext, {"email_sender": outbox, "job_queue": queue})
    assert await dispatch_notifications(ctx) == 1
    # El aviso de prueba no tiene un presupuesto de verdad: su compositor es otro.
    monkeypatch.setitem(notice_composers.COMPOSERS, KIND, compose_ok)
    [job] = queue.jobs
    await send_notification(ctx, **cast(dict[str, Any], job.kwargs))
    assert [email.to for email in outbox.sent] == ["ana@example.com"]
    assert (await row(engines, notification_id))["status"] == "sent"


# --- El envío -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_delivered_notification_is_sent_once(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    """B1: el mismo trabajo dos veces envía un solo correo."""
    a = two_workshops.a
    notification_id, attempt = await claimed(a, client_a)
    outbox = InMemoryEmailSender()
    assert await service.deliver(a, notification_id, attempt, outbox, COMPOSERS) == (
        NotificationStatus.SENT
    )
    assert await service.deliver(a, notification_id, attempt, outbox, COMPOSERS) is None
    assert len(outbox.sent) == 1
    found = await row(engines, notification_id)
    assert (found["status"], found["claimed_at"]) == ("sent", None)
    assert found["sent_at"] is not None


@pytest.mark.asyncio
async def test_b2_a_job_for_another_workshop_does_not_see_the_notification(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    notification_id, attempt = await claimed(two_workshops.a, client_a)
    outbox = InMemoryEmailSender()
    result = await service.deliver(
        two_workshops.b, notification_id, attempt, outbox, COMPOSERS
    )
    assert result is None and outbox.sent == []
    assert (await row(engines, notification_id))["status"] == "claimed"


@pytest.mark.asyncio
async def test_b3_the_same_send_twice_at_once_sends_one_email(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    """El mismo trabajo ejecutado dos veces a la vez (SAQ lo relanza al tomarlo
    por abandonado): la primera ejecución tiene la fila bloqueada mientras habla
    con el SMTP, y la segunda no envía nada. Sin el bloqueo, las dos leerían el
    aviso reclamado y saldrían dos correos."""
    a = two_workshops.a
    notification_id, attempt = await claimed(a, client_a)
    slow = SlowSender()
    first = asyncio.create_task(
        service.deliver(a, notification_id, attempt, slow, COMPOSERS)
    )
    await asyncio.wait_for(slow.started.wait(), timeout=5)
    second = asyncio.create_task(
        service.deliver(a, notification_id, attempt, slow, COMPOSERS)
    )
    await asyncio.sleep(GRACE)
    slow.release.set()
    results = await asyncio.wait_for(asyncio.gather(first, second), timeout=10)
    assert sorted(results, key=str) == sorted([NotificationStatus.SENT, None], key=str)
    assert len(slow.sent) == 1


@pytest.mark.asyncio
async def test_b4_a_failure_after_delivering_is_unknown_and_never_retried(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    a = two_workshops.a
    notification_id, attempt = await claimed(a, client_a)
    sender = FailingSender(EmailDeliveryUnknownError("corte en DATA"))
    assert await service.deliver(a, notification_id, attempt, sender, COMPOSERS) == (
        NotificationStatus.UNKNOWN
    )
    found = await row(engines, notification_id)
    assert (found["status"], found["failure_reason"], found["next_attempt_at"]) == (
        "unknown",
        "delivery_unknown",
        None,
    )
    queue = InMemoryJobQueue()
    assert await service.dispatch(a, queue, email_enabled=True) == 0
    assert await workshops_with_due_notifications() == []


@pytest.mark.asyncio
async def test_an_unclassified_error_while_sending_is_unknown(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    """Un error que el emisor no clasificó pudo llegar después de entregar: lo
    prudente es no reintentarlo."""
    a = two_workshops.a
    notification_id, attempt = await claimed(a, client_a)
    sender = FailingSender(RuntimeError("inesperado"))
    assert await service.deliver(a, notification_id, attempt, sender, COMPOSERS) == (
        NotificationStatus.UNKNOWN
    )


@pytest.mark.asyncio
async def test_b5_a_failure_before_delivering_is_retried_up_to_three_times(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    a = two_workshops.a
    notification_id = await create(a, client_a)
    sender = FailingSender(EmailNotSentError("550 rechazado", smtp_code=550))

    for attempt in range(1, MAX_ATTEMPTS + 1):
        queue = InMemoryJobQueue()
        assert await service.dispatch(a, queue, email_enabled=True) == 1
        assert queue.jobs[0].kwargs["attempt"] == attempt
        assert await service.deliver(
            a, notification_id, attempt, sender, COMPOSERS
        ) == (NotificationStatus.FAILED)
        found = await row(engines, notification_id)
        assert (found["status"], found["failure_reason"], found["smtp_code"]) == (
            "failed",
            "not_sent",
            550,
        )
        if attempt < MAX_ATTEMPTS:
            # Se reintentará, pero no antes de tiempo (5 y 30 minutos).
            wait = found["next_attempt_at"] - found["updated_at"]
            assert wait >= timedelta(minutes=5 if attempt == 1 else 30) - timedelta(
                seconds=5
            )
            assert await service.dispatch(a, queue, email_enabled=True) == 0
            await age(engines, notification_id, "next_attempt_at", "1 hour")

    assert sender.calls == MAX_ATTEMPTS
    assert found["next_attempt_at"] is None  # sin más intentos
    assert await service.dispatch(a, InMemoryJobQueue(), email_enabled=True) == 0


@pytest.mark.asyncio
async def test_b6_an_abandoned_claim_becomes_unknown_and_is_never_sent(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    a = two_workshops.a
    notification_id, attempt = await claimed(a, client_a)
    assert await service.expire_abandoned(a) == 0  # aún no
    await age(engines, notification_id, "claimed_at", "11 minutes")
    assert await workshops_with_abandoned_notifications(timedelta(minutes=10)) == [a]

    assert await service.expire_abandoned(a) == 1
    found = await row(engines, notification_id)
    assert (found["status"], found["failure_reason"]) == ("unknown", "abandoned")
    # El trabajo que se encoló, si llega tarde, ya no envía nada.
    outbox = InMemoryEmailSender()
    assert await service.deliver(a, notification_id, attempt, outbox, COMPOSERS) is None
    assert outbox.sent == []
    assert await service.dispatch(a, InMemoryJobQueue(), email_enabled=True) == 0


@pytest.mark.asyncio
async def test_the_abandoned_sweep_does_not_step_on_a_send_in_progress(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    """Un envío que tardó en empezar y sigue hablando con el SMTP tiene la fila
    bloqueada: el barrido se la salta, y el envío termina como `sent`."""
    a = two_workshops.a
    notification_id, attempt = await claimed(a, client_a)
    await age(engines, notification_id, "claimed_at", "11 minutes")
    slow = SlowSender()
    sending = asyncio.create_task(
        service.deliver(a, notification_id, attempt, slow, COMPOSERS)
    )
    await asyncio.wait_for(slow.started.wait(), timeout=5)
    assert await service.expire_abandoned(a) == 0
    slow.release.set()
    assert await sending == NotificationStatus.SENT
    assert (await row(engines, notification_id))["status"] == "sent"


# --- Los compositores -------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (NotificationStatus.SKIPPED, FailureReason.NO_EMAIL),
        (NotificationStatus.CANCELLED, FailureReason.OBSOLETE),
    ],
)
async def test_a_composer_can_decide_not_to_send(
    engines: Engines,
    two_workshops: TwoWorkshops,
    client_a: UUID,
    status: NotificationStatus,
    reason: FailureReason,
) -> None:
    a = two_workshops.a
    notification_id, attempt = await claimed(a, client_a)

    async def nothing(session: AsyncSession, n: Notification) -> NotDelivered:
        return NotDelivered(status, reason)

    outbox = InMemoryEmailSender()
    assert await service.deliver(
        a, notification_id, attempt, outbox, {KIND: nothing}
    ) == (status)
    assert outbox.sent == []
    found = await row(engines, notification_id)
    assert (found["status"], found["failure_reason"]) == (status.value, reason.value)


@pytest.mark.asyncio
async def test_a_composer_that_breaks_the_transaction_still_records_the_failure(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    """Un error de SQL al escribir el correo no aborta la transacción del envío
    (va en un savepoint): el fallo se guarda y se reintentará."""
    a = two_workshops.a
    notification_id, attempt = await claimed(a, client_a)

    async def broken(session: AsyncSession, n: Notification) -> Email:
        await session.execute(text("SELECT * FROM no_such_table"))
        raise AssertionError("no llega")

    outbox = InMemoryEmailSender()
    assert await service.deliver(
        a, notification_id, attempt, outbox, {KIND: broken}
    ) == (NotificationStatus.FAILED)
    found = await row(engines, notification_id)
    assert (found["status"], found["failure_reason"]) == ("failed", "compose_failed")
    assert found["next_attempt_at"] is not None


@pytest.mark.asyncio
async def test_a_kind_without_composer_fails_without_retries(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    a = two_workshops.a
    notification_id, attempt = await claimed(a, client_a)
    outbox = InMemoryEmailSender()
    assert await service.deliver(a, notification_id, attempt, outbox, {}) == (
        NotificationStatus.FAILED
    )
    found = await row(engines, notification_id)
    assert (found["failure_reason"], found["next_attempt_at"]) == ("no_composer", None)


# --- La base de datos: los estados finales no se reabren --------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["app", "platform", "owner"])
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE notifications SET status = 'pending' WHERE id = :n",
        (
            "UPDATE notifications SET status = 'claimed', attempts = attempts + 1,"
            " claimed_at = clock_timestamp(), sent_at = NULL WHERE id = :n"
        ),
        "DELETE FROM notifications WHERE id = :n",
        "UPDATE notifications SET dedupe_key = 'otra' WHERE id = :n",
    ],
)
async def test_a_sent_notification_cannot_be_reopened_by_anyone(
    engines: Engines,
    two_workshops: TwoWorkshops,
    client_a: UUID,
    role: str,
    statement: str,
) -> None:
    a = two_workshops.a
    notification_id, attempt = await claimed(a, client_a)
    await service.deliver(a, notification_id, attempt, InMemoryEmailSender(), COMPOSERS)
    async with getattr(engines, role).connect() as conn:
        await set_workshops(conn, a)
        # La aplicación ni siquiera tiene el permiso de borrar ni de cambiar el
        # motivo; los otros dos roles los tienen, y el trigger los para.
        with pytest.raises(DBAPIError):
            await conn.execute(text(statement), {"n": notification_id})
        await conn.rollback()
    assert (await row(engines, notification_id))["status"] == "sent"


@pytest.mark.asyncio
async def test_an_unknown_notification_cannot_be_retried(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    a = two_workshops.a
    notification_id, attempt = await claimed(a, client_a)
    await service.deliver(
        a,
        notification_id,
        attempt,
        FailingSender(EmailDeliveryUnknownError("x")),
        COMPOSERS,
    )
    async with engines.platform.connect() as conn:
        with pytest.raises(DBAPIError, match="cannot go from unknown to claimed"):
            await conn.execute(
                text(
                    "UPDATE notifications SET status = 'claimed',"
                    " attempts = attempts + 1, claimed_at = clock_timestamp(),"
                    " failure_reason = NULL WHERE id = :n"
                ),
                {"n": notification_id},
            )
        await conn.rollback()


@pytest.mark.asyncio
async def test_each_claim_must_count_one_attempt(
    engines: Engines, two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    """Un reclamo que no sumara su intento dejaría reintentar sin fin."""
    notification_id = await create(two_workshops.a, client_a)
    async with engines.platform.connect() as conn:
        with pytest.raises(DBAPIError, match="wrong attempts"):
            await conn.execute(
                text(
                    "UPDATE notifications SET status = 'claimed',"
                    " claimed_at = clock_timestamp() WHERE id = :n"
                ),
                {"n": notification_id},
            )
        await conn.rollback()


@pytest.mark.asyncio
async def test_the_scheduler_only_finds_workshops_with_due_notifications(
    two_workshops: TwoWorkshops, client_a: UUID
) -> None:
    assert await workshops_with_due_notifications() == []
    await create(two_workshops.a, client_a)
    assert await workshops_with_due_notifications() == [two_workshops.a]
