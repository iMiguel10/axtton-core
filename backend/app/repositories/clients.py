from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_client_names(session: AsyncSession) -> list[str]:
    """Nombres de los clientes visibles.

    Fíjate en que la consulta NO filtra por taller: lo hace RLS. En el código
    definitivo los repositorios filtrarán además por taller (defensa en dos
    capas); aquí se omite a propósito para ver que RLS basta por sí sola.
    """
    result = await session.execute(text("SELECT name FROM clients ORDER BY name"))
    return list(result.scalars())
