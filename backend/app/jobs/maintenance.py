"""Limpieza programada (F5 paso 1): corre con correo o sin él."""

import logging

from saq import CronJob
from saq.types import Context

from app.domain.portal import LINK_RETENTION
from app.platform.scheduler import workshops_with_expired_links
from app.services import portal_auth as portal_auth_service

logger = logging.getLogger(__name__)

# Una pasada recorre todos los talleres con algo que borrar. Si no terminara, lo
# que quedase lo recoge la del día siguiente.
PURGE_TIMEOUT_SECONDS = 300


async def purge_portal_links(ctx: Context) -> int:
    """Borra los enlaces del portal caducados hace más de LINK_RETENTION.

    Un taller que falla no para a los demás: queda en el registro y lo intenta
    la pasada siguiente.
    """
    deleted = 0
    for workshop_id in await workshops_with_expired_links(LINK_RETENTION):
        try:
            deleted += await portal_auth_service.purge_expired_links(workshop_id)
        except Exception:
            logger.exception("No se pudieron borrar los enlaces de %s", workshop_id)
    logger.info("Enlaces del portal borrados: %d", deleted)
    return deleted


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
