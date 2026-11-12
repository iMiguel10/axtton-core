"""Limpieza programada (F5 paso 1): corre con correo o sin él."""

from saq import CronJob
from saq.types import Context

from app.domain.portal import LINK_RETENTION
from app.jobs.common import each_workshop
from app.platform.scheduler import workshops_with_expired_links
from app.services import portal_auth as portal_auth_service

# Una pasada recorre todos los talleres con algo que borrar. Si no terminara, lo
# que quedase lo recoge la del día siguiente.
PURGE_TIMEOUT_SECONDS = 300


async def purge_portal_links(ctx: Context) -> int:
    """Borra los enlaces del portal caducados hace más de LINK_RETENTION."""
    return await each_workshop(
        await workshops_with_expired_links(LINK_RETENTION),
        portal_auth_service.purge_expired_links,
        "Enlaces del portal borrados",
    )


def maintenance_cron_jobs() -> list[CronJob[Context]]:
    return [
        CronJob(
            purge_portal_links,
            # Cada día a las 3:40 UTC, de madrugada en España.
            cron="40 3 * * *",
            timeout=PURGE_TIMEOUT_SECONDS,
            retries=1,
        )
    ]
