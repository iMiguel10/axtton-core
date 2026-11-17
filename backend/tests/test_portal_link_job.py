"""El enlace del portal se envía desde el worker (F5 paso 8, arquitectura §8).

La API solo encola el taller y el email, sin mirar nada (RF-41), y nunca el
token: el worker emite el enlace al enviarlo. Si el correo no salió, ese enlace
se revoca y el siguiente intento emite otro; si no se sabe, no se reintenta.
"""

from collections.abc import Iterator
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.api.deps import get_email_sender, get_job_queue
from app.domain.portal import (
    LINK_JOB_KEEP,
    LINK_RETRY_DELAY,
    LINK_SEND_ATTEMPTS,
)
from app.infra.email import (
    DisabledEmailSender,
    Email,
    EmailDeliveryUnknownError,
    EmailNotSentError,
    InMemoryEmailSender,
)
from app.infra.queue import InMemoryJobQueue
from app.jobs.context import WorkerContext
from app.jobs.portal import send_portal_link
from app.main import app
from app.services import portal_auth as portal_auth_service
from app.services.portal_auth import LinkNotSentError, LinkSendOutcome
from app.worker import settings as worker_settings
from tests.conftest import Engines, TwoWorkshops
from tests.test_concurrency import dispose_global_engines  # noqa: F401 (autouse)
from tests.test_portal_auth import add_client, consume, links_in, new_email


class Refusing(InMemoryEmailSender):
    """El servidor rechaza el correo: no salió. Su texto lleva el email, como
    hacen muchos servidores reales."""

    async def send(self, email: Email) -> None:
        raise EmailNotSentError(f"550 {email.to}: mailbox unavailable", smtp_code=550)


class CutOff(InMemoryEmailSender):
    """La conexión se corta con el mensaje en vuelo: pudo llegar."""

    async def send(self, email: Email) -> None:
        raise EmailDeliveryUnknownError("connection lost after DATA")


@pytest.fixture
def queue() -> Iterator[InMemoryJobQueue]:
    """Lo que la API encola, sin ejecutarlo, con correo configurado."""
    jobs = InMemoryJobQueue()
    app.dependency_overrides[get_job_queue] = lambda: jobs
    app.dependency_overrides[get_email_sender] = lambda: InMemoryEmailSender()
    yield jobs
    app.dependency_overrides.pop(get_job_queue, None)
    app.dependency_overrides.pop(get_email_sender, None)


async def request_link(client: AsyncClient, workshop_id: UUID, email: str) -> int:
    response = await client.post(
        "/api/v1/portal/auth/request-link",
        json={"workshop_id": str(workshop_id), "email": email},
    )
    return response.status_code


async def links_of(engines: Engines, email: str) -> list[dict[str, Any]]:
    async with engines.platform.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT l.* FROM portal_links l JOIN clients c ON c.id = l.client_id"
                " WHERE c.email = :e ORDER BY l.created_at"
            ),
            {"e": email},
        )
        return [dict(row) for row in rows.mappings()]


# --- La API encola ------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_api_enqueues_the_workshop_and_email_never_a_token(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    queue: InMemoryJobQueue,
) -> None:
    email = new_email()
    await add_client(engines, two_workshops.a, email)
    assert await request_link(client, two_workshops.a, email.upper()) == 202

    [job] = queue.jobs
    assert job.job == "send_portal_link"
    # Normalizado, como se guarda; y nada más: ni token ni cliente.
    assert job.kwargs == {"workshop_id": str(two_workshops.a), "email": email}
    assert (job.max_attempts, job.retry_delay_seconds, job.keep_seconds) == (
        LINK_SEND_ATTEMPTS,
        LINK_RETRY_DELAY.total_seconds(),
        LINK_JOB_KEEP.total_seconds(),
    )
    # La API no emitió ningún enlace: lo hará el worker al enviar.
    assert await links_of(engines, email) == []


@pytest.mark.asyncio
async def test_the_api_enqueues_the_same_whoever_asks(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    queue: InMemoryJobQueue,
) -> None:
    """RF-41: sin mirar si el email es de un cliente ni si el taller existe, la
    respuesta y lo encolado no pueden delatarlo."""
    known = new_email()
    await add_client(engines, two_workshops.a, known)
    for workshop_id, email in (
        (two_workshops.a, known),
        (two_workshops.a, new_email()),
        (uuid4(), known),
    ):
        assert await request_link(client, workshop_id, email) == 202
    assert [job.job for job in queue.jobs] == ["send_portal_link"] * 3


@pytest.mark.asyncio
async def test_without_smtp_nothing_is_enqueued(
    client: AsyncClient,
    engines: Engines,
    two_workshops: TwoWorkshops,
    queue: InMemoryJobQueue,
) -> None:
    app.dependency_overrides[get_email_sender] = lambda: DisabledEmailSender()
    email = new_email()
    await add_client(engines, two_workshops.a, email)
    assert await request_link(client, two_workshops.a, email) == 202
    assert queue.jobs == []


@pytest.mark.asyncio
async def test_with_the_queue_down_the_answer_is_the_same(
    client: AsyncClient, engines: Engines, two_workshops: TwoWorkshops
) -> None:
    app.dependency_overrides[get_job_queue] = lambda: InMemoryJobQueue(fail=True)
    app.dependency_overrides[get_email_sender] = lambda: InMemoryEmailSender()
    try:
        email = new_email()
        await add_client(engines, two_workshops.a, email)
        assert await request_link(client, two_workshops.a, email) == 202
    finally:
        app.dependency_overrides.pop(get_job_queue, None)
        app.dependency_overrides.pop(get_email_sender, None)


# --- El worker envía ----------------------------------------------------------


@pytest.mark.asyncio
async def test_the_worker_sends_a_link_that_opens_the_portal(
    client: AsyncClient, engines: Engines, two_workshops: TwoWorkshops
) -> None:
    email = new_email()
    await add_client(engines, two_workshops.a, email)
    outbox = InMemoryEmailSender()
    context = cast(WorkerContext, {"email_sender": outbox})
    outcome = await send_portal_link(
        context, workshop_id=str(two_workshops.a), email=email
    )
    assert outcome == "sent"
    [sent] = outbox.sent
    assert sent.to == email
    [(workshop_id, token)] = links_in(sent)
    assert workshop_id == two_workshops.a
    assert (await consume(client, workshop_id, token)).status_code == 204


@pytest.mark.asyncio
async def test_the_worker_is_registered_with_the_link_job() -> None:
    assert send_portal_link in worker_settings["functions"]


@pytest.mark.asyncio
async def test_nothing_goes_out_to_someone_without_access(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    archived, of_b = new_email(), new_email()
    archived_id = await add_client(engines, two_workshops.a, archived)
    await add_client(engines, two_workshops.b, of_b)
    async with engines.platform.begin() as conn:
        await conn.execute(
            text("UPDATE clients SET archived_at = clock_timestamp() WHERE id = :c"),
            {"c": archived_id},
        )
    outbox = InMemoryEmailSender()
    for workshop_id, email in (
        (two_workshops.a, new_email()),
        (two_workshops.a, archived),
        (two_workshops.a, of_b),
        (uuid4(), of_b),
    ):
        outcome = await portal_auth_service.send_link(workshop_id, email, outbox)
        assert outcome == LinkSendOutcome.NO_ACCESS
    assert outbox.sent == []
    assert await links_of(engines, archived) == []
    assert await links_of(engines, of_b) == []


@pytest.mark.asyncio
async def test_a_worker_without_smtp_issues_nothing(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    email = new_email()
    await add_client(engines, two_workshops.a, email)
    outcome = await portal_auth_service.send_link(
        two_workshops.a, email, DisabledEmailSender()
    )
    assert outcome == LinkSendOutcome.EMAIL_DISABLED
    assert await links_of(engines, email) == []


@pytest.mark.asyncio
async def test_a_link_that_did_not_go_out_is_revoked_and_retried_with_another(
    client: AsyncClient, engines: Engines, two_workshops: TwoWorkshops
) -> None:
    email = new_email()
    await add_client(engines, two_workshops.a, email)
    with pytest.raises(LinkNotSentError) as refused:
        await portal_auth_service.send_link(two_workshops.a, email, Refusing())
    # SAQ guarda el error con el trabajo: sin el texto del servidor, que
    # llevaba el email.
    assert refused.value.smtp_code == 550
    assert email not in str(refused.value)
    assert refused.value.__cause__ is None
    [first] = await links_of(engines, email)
    assert first["revoked_at"] is not None

    # El siguiente intento emite otro enlace, que sí vale.
    outbox = InMemoryEmailSender()
    assert (
        await portal_auth_service.send_link(two_workshops.a, email, outbox)
        == LinkSendOutcome.SENT
    )
    [(workshop_id, token)] = links_in(outbox.sent[0])
    assert (await consume(client, workshop_id, token)).status_code == 204
    revoked, used = await links_of(engines, email)
    assert revoked["id"] == first["id"] and used["used_at"] is not None


@pytest.mark.asyncio
async def test_a_link_that_may_have_arrived_is_not_retried(
    engines: Engines, two_workshops: TwoWorkshops
) -> None:
    """Pudo llegar: no se reintenta (saldrían dos) ni se revoca (si llegó, que
    sirva)."""
    email = new_email()
    await add_client(engines, two_workshops.a, email)
    outcome = await portal_auth_service.send_link(two_workshops.a, email, CutOff())
    assert outcome == LinkSendOutcome.DELIVERY_UNKNOWN
    [link] = await links_of(engines, email)
    assert (link["revoked_at"], link["used_at"]) == (None, None)
