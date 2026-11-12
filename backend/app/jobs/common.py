"""Lo que comparten las tareas programadas."""

import logging
from collections.abc import Awaitable, Callable, Iterable
from uuid import UUID

logger = logging.getLogger(__name__)


async def each_workshop(
    workshop_ids: Iterable[UUID], work: Callable[[UUID], Awaitable[int]], what: str
) -> int:
    """Llama a `work` taller a taller y suma lo que devuelve. Un taller que falla
    no para a los demás: queda en el registro y lo intenta la pasada siguiente."""
    done = 0
    for workshop_id in workshop_ids:
        try:
            done += await work(workshop_id)
        except Exception:
            logger.exception("%s: falló el taller %s", what, workshop_id)
    logger.info("%s: %d", what, done)
    return done
