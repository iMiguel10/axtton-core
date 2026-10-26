from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client, Vehicle, VehicleOwnership


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


async def get(session: AsyncSession, vehicle_id: UUID) -> Vehicle | None:
    """Bajo RLS: un vehículo de otro taller no existe (None, y por tanto 404)."""
    return await session.get(Vehicle, vehicle_id)


async def get_for_update(session: AsyncSession, vehicle_id: UUID) -> Vehicle | None:
    """El vehículo, bloqueado hasta el final de la transacción.

    Para cambiar el titular: dos cambios a la vez sobre el mismo vehículo se
    ponen en fila aquí, y el segundo ve ya la versión que dejó el primero.
    populate_existing: si el vehículo ya estaba en la sesión, se recarga con lo
    que hay en la base al obtener el bloqueo, no con lo que se leyó antes.
    """
    query = (
        select(Vehicle)
        .where(Vehicle.id == vehicle_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(query)).one_or_none()


async def get_for_share(session: AsyncSession, vehicle_id: UUID) -> Vehicle | None:
    """El vehículo, con un bloqueo compartido hasta el final de la transacción.

    Para abrir una orden: su cliente es el titular de ese momento (invariante
    7). Con el bloqueo, un cambio de titular a la vez (que pide FOR UPDATE)
    espera a que la orden se abra, o la orden espera al cambio y ve el titular
    nuevo; nunca un titular a medio cambiar. Dos aperturas no se esperan entre sí.
    """
    query = (
        select(Vehicle)
        .where(Vehicle.id == vehicle_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(query)).one_or_none()


async def db_now(session: AsyncSession) -> datetime:
    """La hora de la base de datos. El fin de un periodo y el inicio del
    siguiente tienen que ser el mismo instante y venir del mismo reloj que los
    demás `created_at`."""
    now = await session.scalar(select(func.clock_timestamp()))
    assert now is not None
    return now


async def plate_taken(
    session: AsyncSession, plate_normalized: str, *, except_id: UUID | None = None
) -> bool:
    query = select(Vehicle.id).where(Vehicle.plate_normalized == plate_normalized)
    if except_id is not None:
        query = query.where(Vehicle.id != except_id)
    return (await session.scalar(query.limit(1))) is not None


async def vin_taken(
    session: AsyncSession, vin: str, *, except_id: UUID | None = None
) -> bool:
    query = select(Vehicle.id).where(Vehicle.vin == vin)
    if except_id is not None:
        query = query.where(Vehicle.id != except_id)
    return (await session.scalar(query.limit(1))) is not None


async def current_ownership(
    session: AsyncSession, vehicle_id: UUID
) -> VehicleOwnership | None:
    query = select(VehicleOwnership).where(
        VehicleOwnership.vehicle_id == vehicle_id, VehicleOwnership.ended_at.is_(None)
    )
    return (await session.scalars(query)).one_or_none()


async def ownership_history(
    session: AsyncSession, vehicle_id: UUID
) -> list[tuple[VehicleOwnership, Client]]:
    """Todos los periodos del vehículo, el más reciente primero (RF-13)."""
    rows = await session.execute(
        select(VehicleOwnership, Client)
        .join(Client, Client.id == VehicleOwnership.client_id)
        .where(VehicleOwnership.vehicle_id == vehicle_id)
        .order_by(VehicleOwnership.started_at.desc())
    )
    return [(ownership, client) for ownership, client in rows]


async def list_page(
    session: AsyncSession,
    *,
    query: str | None,
    plate_query: str | None,
    owner_id: UUID | None,
    limit: int,
    offset: int,
) -> list[tuple[Vehicle, Client | None]]:
    """Vehículos del taller fijado con su titular actual, por matrícula.

    `plate_query` es `query` ya normalizada como matrícula: así "1234-bcd" encuentra
    "1234 BCD". La búsqueda única del mostrador llega en el paso 6 de F2.
    """
    current = VehicleOwnership.ended_at.is_(None)
    statement = (
        select(Vehicle, Client)
        .outerjoin(
            VehicleOwnership, (VehicleOwnership.vehicle_id == Vehicle.id) & current
        )
        .outerjoin(Client, Client.id == VehicleOwnership.client_id)
    )
    if owner_id is not None:
        statement = statement.where(VehicleOwnership.client_id == owner_id)
    if query:
        pattern = f"%{_escape_like(query)}%"
        conditions = [Vehicle.make.ilike(pattern), Vehicle.model.ilike(pattern)]
        if plate_query:
            plate_pattern = f"%{_escape_like(plate_query)}%"
            conditions += [
                Vehicle.plate_normalized.like(plate_pattern),
                Vehicle.vin.like(plate_pattern),
            ]
        statement = statement.where(or_(*conditions))
    rows = await session.execute(
        statement.order_by(Vehicle.plate_normalized, Vehicle.id)
        .limit(limit)
        .offset(offset)
    )
    return [(vehicle, client) for vehicle, client in rows]


async def suggestions(
    session: AsyncSession,
    field: Literal["make", "model"],
    prefix: str,
    make: str | None,
    limit: int,
) -> list[str]:
    """Lo que el taller ya ha escrito (RF-11), lo más usado primero. Para el
    modelo, solo los de la marca indicada, si se indica."""
    column = Vehicle.make if field == "make" else Vehicle.model
    statement = select(column).where(
        column.is_not(None), column.ilike(f"{_escape_like(prefix)}%")
    )
    if field == "model" and make:
        statement = statement.where(func.lower(Vehicle.make) == make.lower())
    rows = await session.scalars(
        statement.group_by(column).order_by(func.count().desc(), column).limit(limit)
    )
    return [value for value in rows if value is not None]
