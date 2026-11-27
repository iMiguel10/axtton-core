"""El libro de movimientos de stock del taller activo (F7 paso 2, RF-91 a RF-96).

El stock de una pieza es la suma de sus movimientos (invariante 9) y el libro
solo crece (RNF-12): un error se corrige con el movimiento contrario, nunca
editando o borrando. Dos movimientos a la vez nunca se pisan, porque ninguno
lee el stock para escribirlo (RNF-13). La única excepción es el recuento, que sí
lo lee: bloquea la pieza y compara con lo que vio quien contó.

Las salidas de una orden las anota services/used_parts.py (paso 3).
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.domain.inventory import REVERSIBLE_BY_HAND, MovementKind, count_adjustment
from app.domain.work_orders import order_code
from app.models import Part, StockMovement
from app.repositories import parts as part_repo
from app.repositories import stock as stock_repo
from app.services.integrity import flush_or_conflict

# Dos anulaciones del mismo movimiento a la vez: el índice para a la segunda.
UNIQUE = {"uq_stock_movements_reverses_id": "stock_movement_already_reversed"}


def _check_counted(part: Part) -> None:
    """Solo se anota stock de una pieza que se cuenta y está vigente."""
    if part.archived_at is not None:
        raise ConflictError("part_archived")
    if not part.tracks_stock:
        raise ConflictError("part_stock_not_tracked")


async def _counted_part(session: AsyncSession, part_id: UUID) -> Part:
    part = await part_repo.get(session, part_id)
    if part is None:
        raise NotFoundError("part_not_found")
    _check_counted(part)
    return part


async def _add(session: AsyncSession, movement: StockMovement) -> UUID:
    session.add(movement)
    await flush_or_conflict(session, UNIQUE)
    return movement.id


async def record_entry(
    session: AsyncSession,
    workshop_id: UUID,
    employee_id: UUID,
    part_id: UUID,
    *,
    quantity: Decimal,
    unit_cost_cents: int,
    note: str | None,
) -> UUID:
    """Llega mercancía (RF-91). No lee el stock: solo suma una fila."""
    await _counted_part(session, part_id)
    return await _add(
        session,
        StockMovement(
            workshop_id=workshop_id,
            part_id=part_id,
            kind=MovementKind.IN,
            quantity=quantity,
            unit_cost_cents=unit_cost_cents,
            note=note or None,
            employee_id=employee_id,
        ),
    )


async def record_adjustment(
    session: AsyncSession,
    workshop_id: UUID,
    employee_id: UUID,
    part_id: UUID,
    *,
    quantity: Decimal,
    note: str,
) -> UUID:
    """Una rotura, una pérdida o algo que apareció (RF-92), con su motivo."""
    await _counted_part(session, part_id)
    return await _add(
        session,
        StockMovement(
            workshop_id=workshop_id,
            part_id=part_id,
            kind=MovementKind.ADJUSTMENT,
            quantity=quantity,
            note=note,
            employee_id=employee_id,
        ),
    )


async def record_count(
    session: AsyncSession,
    workshop_id: UUID,
    employee_id: UUID,
    part_id: UUID,
    *,
    counted: Decimal,
    expected: Decimal,
    note: str | None,
) -> UUID | None:
    """Un recuento (RF-92): quien contó dice cuántas hay y el stock que veía
    al contar. Si el stock ha cambiado desde entonces (alguien montó o recibió
    una), el ajuste ya no sería el que pensaba: 409 y vuelve a mirar.

    El bloqueo exclusivo de la pieza espera a los movimientos sin confirmar y
    hace esperar a los que lleguen (repositories/stock.py::lock_part). Si lo
    contado coincide con el stock, no se anota nada."""
    part = await stock_repo.lock_part(session, part_id)
    if part is None:
        raise NotFoundError("part_not_found")
    _check_counted(part)
    stock = await stock_repo.stock_of(session, part_id)
    if stock != expected:
        raise ConflictError("stock_changed")
    delta = count_adjustment(counted, stock)
    if delta == 0:
        return None
    return await _add(
        session,
        StockMovement(
            workshop_id=workshop_id,
            part_id=part_id,
            kind=MovementKind.ADJUSTMENT,
            quantity=delta,
            counted_stock=counted,
            note=note or None,
            employee_id=employee_id,
        ),
    )


async def reverse(
    session: AsyncSession,
    workshop_id: UUID,
    employee_id: UUID,
    movement_id: UUID,
    *,
    note: str,
) -> UUID:
    """Anula una entrada o un ajuste mal anotados con el movimiento contrario
    (RNF-12). Se anula una sola vez; una salida se deshace quitando la pieza de
    su orden (paso 3). Vale también con la pieza archivada o sin contar: es
    corregir lo que ya está en el libro."""
    original = await stock_repo.get(session, movement_id)
    if original is None:
        raise NotFoundError("stock_movement_not_found")
    if original.kind not in REVERSIBLE_BY_HAND:
        raise ConflictError("stock_movement_not_reversible")
    if await stock_repo.is_reversed(session, movement_id):
        raise ConflictError("stock_movement_already_reversed")
    return await _add(
        session,
        StockMovement(
            workshop_id=workshop_id,
            part_id=original.part_id,
            kind=MovementKind.REVERSAL,
            quantity=-original.quantity,
            note=note,
            reverses_id=original.id,
            employee_id=employee_id,
        ),
    )


@dataclass(frozen=True)
class MovementView:
    id: UUID
    seq: int
    kind: str
    quantity: Decimal
    # Solo con VIEW_COSTS (especificación §3).
    unit_cost_cents: int | None
    note: str | None
    counted_stock: Decimal | None
    reverses_id: UUID | None
    reversed_by_id: UUID | None
    # La orden de una salida o de su anulación (RF-96), y su código.
    work_order_id: UUID | None
    work_order_code: str | None
    employee_name: str
    created_at: datetime


async def history(
    session: AsyncSession,
    part_id: UUID,
    *,
    show_costs: bool,
    before_seq: int | None,
    limit: int,
) -> list[MovementView]:
    """El historial de una pieza, con el origen de cada movimiento (RF-96)."""
    if await part_repo.get(session, part_id) is None:
        raise NotFoundError("part_not_found")
    rows = await stock_repo.history(
        session, part_id, before_seq=before_seq, limit=limit
    )
    return [
        MovementView(
            id=row.movement.id,
            seq=row.movement.seq,
            kind=row.movement.kind,
            quantity=row.movement.quantity,
            unit_cost_cents=row.movement.unit_cost_cents if show_costs else None,
            note=row.movement.note,
            counted_stock=row.movement.counted_stock,
            reverses_id=row.movement.reverses_id,
            reversed_by_id=row.reversed_by_id,
            work_order_id=row.movement.work_order_id,
            work_order_code=(
                order_code(row.order_year, row.order_number)
                if row.order_year is not None and row.order_number is not None
                else None
            ),
            employee_name=row.employee_name,
            created_at=row.movement.created_at,
        )
        for row in rows
    ]
