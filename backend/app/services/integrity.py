"""Restricciones de la base de datos como errores de la aplicación."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError


async def flush_or_conflict(session: AsyncSession, conflicts: dict[str, str]) -> None:
    """Escribe lo pendiente y traduce a 409 las restricciones que se esperan.

    La comprobación previa de un service ("¿ya existe esta matrícula?") da el
    error amable en el caso normal; esta es la que vale cuando dos personas
    guardan lo mismo a la vez: las dos pasan la comprobación y la restricción
    rechaza a la segunda. Sin traducirla, sería un 500. `conflicts` va de
    nombre de restricción o índice a código de error.
    """
    try:
        await session.flush()
    except IntegrityError as error:
        message = str(error.orig)
        for constraint, code in conflicts.items():
            if f'"{constraint}"' in message:
                raise ConflictError(code) from error
        raise
