"""Vacía todas las tablas de datos. Solo para desarrollo y pruebas.

Usa el rol dueño (axtton_owner) y TRUNCATE porque es lo único que puede vaciar
las tablas append-only: la aplicación no tiene DELETE sobre audit_log, y
TRUNCATE no dispara los triggers de fila ni pasa por RLS. Que ningún rol de la
aplicación pueda hacer esto es justo la garantía que se busca.
"""

import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  (registra todos los modelos)
from app.models.base import Base


async def truncate_all() -> None:
    # La lista sale de los modelos: una tabla nueva queda incluida sin tocar
    # este fichero. alembic_version no es un modelo, así que no se toca.
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    engine = create_async_engine(os.environ["MIGRATIONS_DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {tables}"))
    finally:
        await engine.dispose()
