"""El aviso al cliente de vehículo listo (F5 paso 6, RF-60).

Nace en la transacción del cambio que pone la orden lista
(`work_orders.record_status_change`, invariante 8), con el `seq` de ese cambio en
su `dedupe_key`: deshacerlo cancela el aviso si aún no ha salido, y volver a
marcarla lista es otro cambio, que avisa otra vez (arquitectura §8).

Al enviarlo, el compositor comprueba que la orden sigue lista **por ese mismo
cambio**: si se deshizo, o ya se entregó, el aviso no tiene sentido.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.emails import vehicle_ready_email
from app.domain.notifications import (
    FailureReason,
    NotificationKind,
    ready_key,
    ready_seq,
)
from app.domain.work_orders import WorkOrderStatus
from app.infra.email import Email, compose
from app.models import Notification, WorkOrder
from app.repositories import notifications as notification_repo
from app.repositories import vehicles as vehicle_repo
from app.repositories import work_orders as order_repo
from app.services import notice_context
from app.services import notifications as notification_service
from app.services.notifications import NotDelivered


async def notice_ready(session: AsyncSession, order: WorkOrder, seq: int) -> None:
    """El aviso de la orden lista por el cambio `seq`, en su transacción."""
    await notification_service.create(
        session,
        workshop_id=order.workshop_id,
        kind=NotificationKind.VEHICLE_READY,
        dedupe_key=ready_key(order.id, seq),
        client_id=order.client_id,
        work_order_id=order.id,
    )


async def cancel_ready(session: AsyncSession, order: WorkOrder, seq: int) -> None:
    """Al deshacer el cambio `seq`, su aviso se cancela si aún no ha salido."""
    await notification_repo.cancel_open(
        session, ready_key(order.id, seq), FailureReason.OBSOLETE
    )


async def compose_vehicle_ready(
    session: AsyncSession, notification: Notification
) -> Email | NotDelivered:
    recipient = await notice_context.load(session, notification)
    if isinstance(recipient, NotDelivered):
        return recipient
    order = recipient.order
    last = await order_repo.last_change(session, order.id)
    seq = ready_seq(notification.dedupe_key)
    # Sigue lista por el mismo cambio: si se deshizo, o ya se entregó (o se
    # volvió a marcar, que tiene su propio aviso), este ya no toca.
    if order.status != WorkOrderStatus.READY or last is None or last.seq != seq:
        return notice_context.OBSOLETE
    vehicle = await vehicle_repo.get(session, order.vehicle_id)
    label = notice_context.vehicle_label(
        {"plate": vehicle.plate, "make": vehicle.make, "model": vehicle.model}
        if vehicle is not None
        else None
    )
    workshop = recipient.workshop
    return compose(
        recipient.email,
        vehicle_ready_email(
            notice_context.notice_for(recipient, label),
            unrepaired=order.unrepaired,
            address=workshop.address,
            phone=workshop.phone,
        ),
    )
