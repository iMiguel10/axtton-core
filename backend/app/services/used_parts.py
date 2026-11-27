"""Las piezas usadas en una orden (F7 paso 3, RF-93).

Montar una pieza la anota en la orden y, si la pieza cuenta su stock, saca su
unidad del libro en la misma transacción. Quitarla por error la marca y anota
la anulación de esa salida: nada se borra (RNF-12). El stock puede quedar en
negativo: se marca como incidencia, no impide el trabajo (RF-94).

Lo anotan los dos roles; lo quita quien lo anotó o quien gestiona órdenes, solo
con la orden abierta (decidido por el usuario al planificar F7).
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.domain.inventory import MovementKind
from app.domain.permissions import Action, can
from app.domain.work_orders import CLOSED
from app.models import StockMovement, UsedPart, WorkOrder
from app.repositories import parts as part_repo
from app.repositories import used_parts as used_repo
from app.repositories import vehicles as vehicle_repo
from app.repositories import work_orders as order_repo
from app.repositories import worklog as worklog_repo


def _check_open(order: WorkOrder | None) -> WorkOrder:
    if order is None:
        raise NotFoundError("work_order_not_found")
    if order.status in CLOSED:
        raise ConflictError("work_order_closed")
    return order


async def mount(
    session: AsyncSession,
    workshop_id: UUID,
    employee_id: UUID,
    order_id: UUID,
    *,
    part_id: UUID,
    quantity: Decimal,
) -> UUID:
    """Anota una pieza montada en la orden y, si se cuenta, su salida.

    La orden se bloquea como al registrar un trabajo (FOR NO KEY UPDATE): se
    pone en fila con un cambio de estado, así que una cancelación a la vez
    espera o hace esperar, y nunca queda una orden cancelada con piezas.
    """
    order = _check_open(await order_repo.get_for_activity(session, order_id))
    part = await part_repo.get(session, part_id)
    if part is None:
        raise NotFoundError("part_not_found")
    if part.archived_at is not None:
        raise ConflictError("part_archived")
    used = UsedPart(
        workshop_id=workshop_id,
        work_order_id=order.id,
        part_id=part.id,
        quantity=quantity,
        reference=part.reference,
        description=part.description,
        part_condition=part.part_condition,
        warranty_months=part.warranty_months,
        employee_id=employee_id,
    )
    session.add(used)
    # La pieza usada, escrita antes que su salida, que la referencia.
    await session.flush()
    if part.tracks_stock:
        session.add(
            StockMovement(
                workshop_id=workshop_id,
                part_id=part.id,
                kind=MovementKind.OUT,
                quantity=-quantity,
                work_order_id=order.id,
                used_part_id=used.id,
                employee_id=employee_id,
            )
        )
        await session.flush()
    await worklog_repo.touch_activity(
        session, order.id, await vehicle_repo.db_now(session)
    )
    return used.id


async def remove(
    session: AsyncSession,
    employee_id: UUID,
    role: str,
    order_id: UUID,
    used_part_id: UUID,
) -> None:
    """Quita una pieza anotada por error: la marca y deshace su salida con el
    movimiento contrario. Solo con la orden abierta, y una vez."""
    _check_open(await order_repo.get_for_share(session, order_id))
    used = await used_repo.get_for_update(session, order_id, used_part_id)
    if used is None:
        raise NotFoundError("used_part_not_found")
    if used.employee_id != employee_id and not can(role, Action.MANAGE_ORDERS):
        raise ForbiddenError("not_allowed")
    if used.removed_at is not None:
        raise ConflictError("used_part_already_removed")
    outflow = await used_repo.outflow_of(session, used.id)
    used.removed_at = await vehicle_repo.db_now(session)
    used.removed_by_employee_id = employee_id
    await session.flush()
    if outflow is not None:
        session.add(
            StockMovement(
                workshop_id=used.workshop_id,
                part_id=used.part_id,
                kind=MovementKind.REVERSAL,
                quantity=-outflow.quantity,
                reverses_id=outflow.id,
                work_order_id=used.work_order_id,
                used_part_id=used.id,
                employee_id=employee_id,
            )
        )
        await session.flush()


@dataclass(frozen=True)
class UsedPartView:
    id: UUID
    part_id: UUID
    reference: str
    description: str
    part_condition: str
    warranty_months: int | None
    quantity: Decimal
    employee_id: UUID
    employee_name: str
    created_at: datetime
    removed_at: datetime | None
    removed_by_name: str | None
    # Si quien mira puede quitarla (la orden sigue abierta).
    removable: bool


async def list_for_order(
    session: AsyncSession, employee_id: UUID, role: str, order_id: UUID
) -> list[UsedPartView]:
    order = await order_repo.get(session, order_id)
    if order is None:
        raise NotFoundError("work_order_not_found")
    is_open = order.status not in CLOSED
    return [
        UsedPartView(
            id=row.used_part.id,
            part_id=row.used_part.part_id,
            reference=row.used_part.reference,
            description=row.used_part.description,
            part_condition=row.used_part.part_condition,
            warranty_months=row.used_part.warranty_months,
            quantity=row.used_part.quantity,
            employee_id=row.used_part.employee_id,
            employee_name=row.employee_name,
            created_at=row.used_part.created_at,
            removed_at=row.used_part.removed_at,
            removed_by_name=row.removed_by_name,
            removable=is_open
            and row.used_part.removed_at is None
            and (
                row.used_part.employee_id == employee_id
                or can(role, Action.MANAGE_ORDERS)
            ),
        )
        for row in await used_repo.list_for_order(session, order_id)
    ]
