"""El taller de una dirección del portal por su nombre corto (F4 paso 7, decisión 0007).

Cruza talleres por necesidad: `/portal/{nombre}` no dice de qué taller es hasta
que se busca, y no se puede fijar ningún taller para RLS antes de saberlo. Es una
de las excepciones con nombre de la regla R8 (arquitectura §4).

Devuelve solo el id de un taller activo con ese nombre exacto: ni su nombre (lo da
después la entrada, ya con el taller fijado), ni una lista, ni lo que se parezca.
El nombre corto es público: el taller lo imprime en su resguardo.
"""

from uuid import UUID

from sqlalchemy import select

from app.models import Workshop
from app.platform.db import platform_transaction


async def workshop_id_by_slug(slug: str) -> UUID | None:
    query = select(Workshop.id).where(
        Workshop.portal_slug == slug, Workshop.status == "active"
    )
    async with platform_transaction() as session:
        return await session.scalar(query)
