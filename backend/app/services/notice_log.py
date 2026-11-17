"""Lo que ve el taller de los avisos de una orden (F5 paso 7, RF-69).

Solo lectura: qué se avisó al cliente, qué no salió y por qué. La fila de un
aviso no guarda el email ni el texto del correo (RNF-40), así que no hay nada
que quitar antes de enseñarla.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models import Notification
from app.repositories import notifications as notification_repo
from app.repositories import work_orders as order_repo


@dataclass(frozen=True)
class NoticeView:
    notification: Notification
    # La versión del presupuesto de la que avisa; `None` si no es de uno.
    quote_version_no: int | None


async def notices_of_order(session: AsyncSession, order_id: UUID) -> list[NoticeView]:
    if await order_repo.get(session, order_id) is None:
        raise NotFoundError("work_order_not_found")
    return [
        NoticeView(notification, version_no)
        for notification, version_no in await notification_repo.of_order(
            session, order_id
        )
    ]
