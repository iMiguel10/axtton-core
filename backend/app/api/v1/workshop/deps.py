from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import workshop_transaction


async def workshop_session(
    x_workshop_id: Annotated[UUID, Header()],
) -> AsyncIterator[AsyncSession]:
    """Sesión del taller activo, con RLS ya fijada (arquitectura A6).

    F0: el taller llega en la cabecera X-Workshop-Id y NO se comprueba que el
    usuario trabaje en él, porque todavía no hay usuarios. En F1 esta misma
    dependencia validará el taller contra los empleados activos de la sesión
    (RNF-09). FastAPI convierte el nombre del parámetro x_workshop_id en la
    cabecera X-Workshop-Id y responde 422 si falta o no es un UUID.
    """
    async with workshop_transaction([x_workshop_id]) as session:
        yield session


WorkshopSession = Annotated[AsyncSession, Depends(workshop_session)]
