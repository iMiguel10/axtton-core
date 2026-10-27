"""Aplicar los límites de recursos de un taller (especificación §10, RF-114).

`ensure_room` va al principio de cada alta, antes de cualquier otro bloqueo: así
todas las altas de un recurso se ponen en fila en el mismo sitio y en el mismo
orden, y nadie espera a nadie en círculo. Las del personal, después de
`employee_repo.lock_staff`, que es el primero de todos en ese flujo.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.domain.limits import LIMIT_REACHED, Resource, has_room
from app.repositories import limits as limit_repo


async def ensure_room(
    session: AsyncSession, workshop_id: UUID, resource: Resource
) -> None:
    """Un 409 si el taller ya está en su límite de `resource`; si no, deja el
    recuento bloqueado hasta el final de la transacción."""
    await limit_repo.lock(session, workshop_id, resource)
    used = await limit_repo.usage(session, workshop_id, resource)
    if not has_room(used, await limit_repo.limit_of(session, workshop_id, resource)):
        raise ConflictError(LIMIT_REACHED[resource])


@dataclass(frozen=True)
class Usage:
    resource: Resource
    used: int
    limit: int


async def usage_report(session: AsyncSession, workshop_id: UUID) -> list[Usage]:
    """Lo gastado de cada límite, para que el administrador lo vea antes de
    llegar al tope ("Clientes: 940 de 1.000")."""
    return [
        Usage(
            resource,
            await limit_repo.usage(session, workshop_id, resource),
            await limit_repo.limit_of(session, workshop_id, resource),
        )
        for resource in Resource
    ]
