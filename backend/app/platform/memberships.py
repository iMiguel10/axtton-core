"""Los talleres en los que trabaja una persona (selector de taller, RF-08).

Cruza talleres por necesidad: hay que saber cuáles son antes de poder fijar
ninguno para RLS. Es una de las excepciones con nombre de la regla R8
(arquitectura §4). Devuelve solo los talleres DE LA PROPIA PERSONA, y solo su
nombre y el rol que tiene en cada uno.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from app.models import Employee, User, Workshop
from app.platform.db import platform_transaction


@dataclass(frozen=True)
class Membership:
    workshop_id: UUID
    workshop_name: str
    role: str


async def list_for_user(supertokens_user_id: str) -> list[Membership]:
    query = (
        select(Workshop.id, Workshop.name, Employee.role)
        .join(Employee, Employee.workshop_id == Workshop.id)
        .join(User, User.id == Employee.user_id)
        .where(
            User.supertokens_user_id == supertokens_user_id,
            Employee.active,
            Workshop.status == "active",
        )
        .order_by(Workshop.name)
    )
    async with platform_transaction() as session:
        return [Membership(*row) for row in await session.execute(query)]
