from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import workshop_transaction


@dataclass(frozen=True)
class WorkshopContext:
    """Lo que necesita un endpoint del taller: el taller activo y su sesión."""

    workshop_id: UUID
    session: AsyncSession


async def workshop_context(
    x_workshop_id: Annotated[UUID, Header()],
) -> AsyncIterator[WorkshopContext]:
    """Taller activo con RLS ya fijada (arquitectura A6).

    F0: el taller llega en la cabecera X-Workshop-Id y NO se comprueba que el
    usuario trabaje en él, porque todavía no hay usuarios. En F1 esta misma
    dependencia validará el taller contra los empleados activos de la sesión
    (RNF-09). FastAPI convierte el nombre del parámetro x_workshop_id en la
    cabecera X-Workshop-Id y responde 422 si falta o no es un UUID.

    La transacción se confirma al terminar el endpoint, o se deshace si lanza
    una excepción: nada queda a medias.
    """
    async with workshop_transaction([x_workshop_id]) as session:
        yield WorkshopContext(workshop_id=x_workshop_id, session=session)


Workshop = Annotated[WorkshopContext, Depends(workshop_context)]
