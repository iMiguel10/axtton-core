"""La bandeja de avisos (F5 paso 4, arquitectura §8): el despachador, el envío
de cada aviso y el barrido de reclamos abandonados.

Corren también sin SMTP: el despachador marca entonces los avisos `skipped`, y
el taller ve que no se avisó y por qué (RNF-32).
"""

from functools import partial
from uuid import UUID

from saq import CronJob

from app.domain.notifications import ABANDONED_AFTER
from app.jobs.common import each_workshop
from app.jobs.context import WorkerContext
from app.platform.scheduler import (
    workshops_with_abandoned_notifications,
    workshops_with_due_notifications,
)
from app.services import notifications as notification_service
from app.services.notice_composers import COMPOSERS

# Una pasada recorre los talleres con algo que enviar; cada uno, como mucho
# DISPATCH_BATCH avisos. Lo que no quepa, en la del minuto siguiente.
SWEEP_TIMEOUT_SECONDS = 50


async def dispatch_notifications(ctx: WorkerContext) -> int:
    return await each_workshop(
        await workshops_with_due_notifications(),
        partial(
            notification_service.dispatch,
            queue=ctx["job_queue"],
            email_enabled=ctx["email_sender"].enabled,
        ),
        "Avisos encolados",
    )


async def send_notification(
    ctx: WorkerContext, *, workshop_id: str, notification_id: str, attempt: int
) -> None:
    """El envío de un aviso. Solo ids: el resto se lee de la base de datos."""
    await notification_service.deliver(
        UUID(workshop_id),
        UUID(notification_id),
        attempt,
        ctx["email_sender"],
        COMPOSERS,
    )


async def expire_abandoned_notifications(ctx: WorkerContext) -> int:
    return await each_workshop(
        await workshops_with_abandoned_notifications(ABANDONED_AFTER),
        notification_service.expire_abandoned,
        "Avisos abandonados",
    )


def notification_cron_jobs() -> list[CronJob[WorkerContext]]:
    return [
        CronJob(
            dispatch_notifications,
            cron="* * * * *",
            timeout=SWEEP_TIMEOUT_SECONDS,
            retries=1,
        ),
        CronJob(
            expire_abandoned_notifications,
            cron="*/10 * * * *",
            timeout=SWEEP_TIMEOUT_SECONDS,
            retries=1,
        ),
    ]
