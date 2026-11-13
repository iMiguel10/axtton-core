"""Presupuestos (F5 paso 2): marcar como caducadas las versiones fuera de plazo.
Corre con correo o sin él."""

from saq import CronJob

from app.jobs.common import each_workshop
from app.jobs.context import WorkerContext
from app.platform.scheduler import workshops_with_overdue_quotes
from app.services import quotes as quote_service

# Cada taller, como mucho EXPIRY_BATCH versiones por pasada.
EXPIRE_TIMEOUT_SECONDS = 300


async def expire_quotes(ctx: WorkerContext) -> int:
    """Escribe `expired` en las versiones enviadas cuya validez ya pasó (RF-33)."""
    return await each_workshop(
        await workshops_with_overdue_quotes(),
        quote_service.expire_overdue,
        "Presupuestos caducados",
    )


def quote_cron_jobs() -> list[CronJob[WorkerContext]]:
    return [
        CronJob(
            expire_quotes,
            # Cada hora (arquitectura §8). La validez acaba al final de un día
            # en la zona del taller; hasta que pasa, ya se lee como caducada.
            cron="5 * * * *",
            timeout=EXPIRE_TIMEOUT_SECONDS,
            retries=1,
        )
    ]
