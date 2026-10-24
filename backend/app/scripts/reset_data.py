"""Vacía todas las tablas de datos. Solo para desarrollo y pruebas.

Usa el rol dueño (axtton_owner) y TRUNCATE porque es lo único que puede vaciar
las tablas append-only: la aplicación no tiene DELETE sobre quote_decisions, y
TRUNCATE no dispara los triggers de fila ni pasa por RLS. Que ningún rol de la
aplicación pueda hacer esto es justo la garantía que se busca.
"""

import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATA_TABLES = (
    "quote_decisions",
    "quote_lines",
    "quotes",
    "work_orders",
    "vehicles",
    "clients",
    "workshops",
)


async def truncate_all() -> None:
    engine = create_async_engine(os.environ["MIGRATIONS_DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {', '.join(DATA_TABLES)}"))
    finally:
        await engine.dispose()
