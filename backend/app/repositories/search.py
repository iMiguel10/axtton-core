"""La búsqueda única del mostrador (RF-14), bajo RLS: solo el taller fijado.

Cada término se compara con una columna normalizada al guardar. No hay índices
trigram: bajo RLS no se usarían (LIKE no es LEAKPROOF; migración 0008search).
Se recorren las filas del taller, nunca las de otro.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.models import Client, Vehicle, VehicleOwnership


def escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def contains_text(column: InstrumentedAttribute[str], text: str) -> ColumnElement[bool]:
    """`column` (ya pasada por search_text) contiene `text`, normalizado en la
    base de datos con la misma función: sin tildes ni mayúsculas."""
    return column.like(func.concat("%", func.search_text(escape_like(text)), "%"))


def starts_with_text(
    column: InstrumentedAttribute[str], text: str
) -> ColumnElement[bool]:
    return column.like(func.concat(func.search_text(escape_like(text)), "%"))


async def vehicles_by_plate(
    session: AsyncSession, plate: str, limit: int
) -> list[tuple[Vehicle, Client | None]]:
    """Vehículos cuya matrícula contiene `plate`, los que empiezan por ella
    primero, con su titular actual."""
    pattern = escape_like(plate)
    rows = await session.execute(
        select(Vehicle, Client)
        .outerjoin(
            VehicleOwnership,
            (VehicleOwnership.vehicle_id == Vehicle.id)
            & VehicleOwnership.ended_at.is_(None),
        )
        .outerjoin(Client, Client.id == VehicleOwnership.client_id)
        .where(Vehicle.plate_normalized.like(f"%{pattern}%"))
        .order_by(
            case((Vehicle.plate_normalized.like(f"{pattern}%"), 0), else_=1),
            Vehicle.plate_normalized,
        )
        .limit(limit)
    )
    return [(vehicle, client) for vehicle, client in rows]


async def clients_by_name_or_phone(
    session: AsyncSession, text: str | None, digits: str | None, limit: int
) -> list[Client]:
    """Clientes cuyo nombre contiene `text` o cuyo teléfono contiene `digits`.

    Primero los no archivados, y entre ellos los que empiezan por lo escrito.
    Los archivados salen también: un cliente que vuelve tras años es el mismo.
    """
    conditions: list[ColumnElement[bool]] = []
    if text:
        conditions.append(contains_text(Client.name_search, text))
    if digits:
        conditions.append(Client.phone_digits.like(f"%{escape_like(digits)}%"))
    if not conditions:
        return []
    starts = starts_with_text(Client.name_search, text) if text else None
    order = [case((Client.archived_at.is_(None), 0), else_=1)]
    if starts is not None:
        order.append(case((starts, 0), else_=1))
    rows = await session.scalars(
        select(Client)
        .where(or_(*conditions))
        .order_by(*order, Client.name, Client.id)
        .limit(limit)
    )
    return list(rows)


async def current_vehicles_of(
    session: AsyncSession, client_ids: Sequence[UUID]
) -> list[tuple[UUID, Vehicle]]:
    """Los vehículos de los que cada cliente es titular hoy, en una consulta."""
    if not client_ids:
        return []
    rows = await session.execute(
        select(VehicleOwnership.client_id, Vehicle)
        .join(Vehicle, Vehicle.id == VehicleOwnership.vehicle_id)
        .where(
            VehicleOwnership.client_id.in_(client_ids),
            VehicleOwnership.ended_at.is_(None),
        )
        .order_by(Vehicle.plate_normalized)
    )
    return [(client_id, vehicle) for client_id, vehicle in rows]
