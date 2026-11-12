"""El planificador del worker (arquitectura §4 y §8): qué hay pendiente en todos
los talleres.

Es una de las vías que cruzan talleres, y **solo busca**: devuelve ids de
talleres (o de filas con su taller), nunca las procesa. Cada trabajo se hace
después en la transacción de su taller, con axtton_app y RLS (`services/`), así
que un fallo al procesar no puede tocar otro taller.
"""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select

from app.models import PortalLink
from app.platform.db import platform_transaction


async def workshops_with_expired_links(retention: timedelta) -> list[UUID]:
    """Los talleres con enlaces del portal caducados hace más de `retention`."""
    query = (
        select(PortalLink.workshop_id)
        .where(PortalLink.expires_at < func.clock_timestamp() - retention)
        .distinct()
    )
    async with platform_transaction() as session:
        return list(await session.scalars(query))
