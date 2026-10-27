"""Vehículos y su titularidad (RF-11, RF-12, RF-13).

Un vehículo tiene en cada momento un único titular: el periodo abierto de
vehicle_ownerships. Se le da al crearlo, y después solo cambia de manos:
cambiar el titular cierra el periodo abierto y abre otro en el mismo instante.
Nunca queda sin titular, y los periodos no se borran.

Todo se ejecuta en la transacción del taller activo (RLS fijada).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.domain.limits import Resource
from app.domain.vehicles import (
    is_valid_plate,
    is_valid_vin,
    normalize_plate,
    normalize_vin,
)
from app.models import AuditEntry, Client, Vehicle, VehicleOwnership
from app.repositories import clients as client_repo
from app.repositories import vehicles as vehicle_repo
from app.services import limits as limit_service
from app.services.integrity import flush_or_conflict

EDITABLE = (
    "plate",
    "vin",
    "make",
    "model",
    "year",
    "fuel",
    "next_itv_date",
    "next_service_date",
    "next_service_km",
)
OPTIONAL_TEXT = ("vin", "make", "model")

# Si dos guardan la misma matrícula o el mismo VIN a la vez, la base de datos
# para al segundo (services/integrity.py).
UNIQUE = {
    "uq_vehicles_workshop_id_plate_normalized": "vehicle_plate_taken",
    "uq_vehicles_workshop_id_vin": "vehicle_vin_taken",
}


@dataclass(frozen=True)
class OwnerView:
    id: UUID
    name: str


@dataclass(frozen=True)
class VehicleView:
    vehicle: Vehicle
    owner: OwnerView | None


@dataclass(frozen=True)
class OwnershipView:
    client: OwnerView
    started_at: datetime
    ended_at: datetime | None


@dataclass(frozen=True)
class VehicleDetail:
    vehicle: Vehicle
    owner: OwnerView
    ownerships: list[OwnershipView]


def _owner(client: Client) -> OwnerView:
    return OwnerView(client.id, client.name)


def _normalized(changes: dict[str, Any]) -> dict[str, Any]:
    """Matrícula y VIN normalizados al guardar, no al buscar (arquitectura §3)."""
    result = dict(changes)
    for field in OPTIONAL_TEXT:
        if field in result and not result[field]:
            result[field] = None
    if "plate" in result:
        result["plate_normalized"] = normalize_plate(result["plate"])
        if not is_valid_plate(result["plate_normalized"]):
            raise ValidationFailedError("invalid_plate")
    if result.get("vin") is not None:
        result["vin"] = normalize_vin(result["vin"])
        if not is_valid_vin(result["vin"]):
            raise ValidationFailedError("invalid_vin")
    return result


async def _check_unique(
    session: AsyncSession, values: dict[str, Any], except_id: UUID | None = None
) -> None:
    """El error amable. La garantía es el índice único (flush_or_conflict)."""
    plate = values.get("plate_normalized")
    if plate and await vehicle_repo.plate_taken(session, plate, except_id=except_id):
        raise ConflictError("vehicle_plate_taken")
    vin = values.get("vin")
    if vin and await vehicle_repo.vin_taken(session, vin, except_id=except_id):
        raise ConflictError("vehicle_vin_taken")


async def _get(session: AsyncSession, vehicle_id: UUID) -> Vehicle:
    vehicle = await vehicle_repo.get(session, vehicle_id)
    if vehicle is None:
        raise NotFoundError("vehicle_not_found")
    return vehicle


def _check_version(vehicle: Vehicle, expected: int) -> None:
    """Bloqueo optimista a nivel HTTP (RNF-15)."""
    if vehicle.version != expected:
        raise ConflictError("modified_by_someone_else")


async def _new_owner(session: AsyncSession, client_id: UUID) -> Client:
    """El cliente que va a ser titular: del taller (si no, no existe) y sin
    archivar (archivar es sacarlo de la circulación)."""
    # Bloqueo compartido: un vehículo no pasa a un cliente mientras se le
    # anonimiza (client_repo.get_locked).
    client = await client_repo.get_locked(session, client_id, shared=True)
    if client is None:
        raise NotFoundError("client_not_found")
    if client.anonymized_at is not None:
        raise ConflictError("client_anonymized")
    if client.archived_at is not None:
        raise ConflictError("client_archived")
    return client


async def list_vehicles(
    session: AsyncSession,
    *,
    query: str | None,
    owner_id: UUID | None,
    limit: int,
    offset: int,
) -> list[VehicleView]:
    query = query.strip() if query else None
    rows = await vehicle_repo.list_page(
        session,
        query=query,
        plate_query=normalize_plate(query) if query else None,
        owner_id=owner_id,
        limit=limit,
        offset=offset,
    )
    return [
        VehicleView(vehicle, _owner(client) if client else None)
        for vehicle, client in rows
    ]


async def get_vehicle(session: AsyncSession, vehicle_id: UUID) -> VehicleDetail:
    """La ficha con su titular actual y todos sus periodos (RF-13)."""
    vehicle = await _get(session, vehicle_id)
    history = await vehicle_repo.ownership_history(session, vehicle_id)
    ownerships = [
        OwnershipView(_owner(client), ownership.started_at, ownership.ended_at)
        for ownership, client in history
    ]
    current = next(o for o in ownerships if o.ended_at is None)
    return VehicleDetail(vehicle, current.client, ownerships)


async def create_vehicle(
    session: AsyncSession, workshop_id: UUID, fields: dict[str, Any], owner_id: UUID
) -> UUID:
    """Un vehículo nace con su titular: el primer periodo empieza al darlo de
    alta, en la misma transacción."""
    # Primero el límite (§10), antes que el bloqueo del titular: todas las altas
    # se ponen en fila en el mismo orden.
    await limit_service.ensure_room(session, workshop_id, Resource.VEHICLES)
    await _new_owner(session, owner_id)
    values = _normalized(fields)
    await _check_unique(session, values)
    vehicle = Vehicle(workshop_id=workshop_id, **values)
    session.add(vehicle)
    await flush_or_conflict(session, UNIQUE)
    session.add(
        VehicleOwnership(
            workshop_id=workshop_id,
            vehicle_id=vehicle.id,
            client_id=owner_id,
            started_at=await vehicle_repo.db_now(session),
        )
    )
    await session.flush()
    return vehicle.id


async def update_vehicle(
    session: AsyncSession,
    vehicle_id: UUID,
    *,
    expected_version: int,
    changes: dict[str, Any],
) -> None:
    vehicle = await _get(session, vehicle_id)
    _check_version(vehicle, expected_version)
    values = _normalized(changes)
    # Solo se comprueba lo que cambia: guardar la propia matrícula escrita de
    # otra forma no choca consigo misma (except_id lo cubre igualmente).
    changed = {
        field: value
        for field, value in values.items()
        if field in ("plate_normalized", "vin") and value != getattr(vehicle, field)
    }
    await _check_unique(session, changed, except_id=vehicle_id)
    for field in (*EDITABLE, "plate_normalized"):
        if field in values:
            setattr(vehicle, field, values[field])
    await flush_or_conflict(session, UNIQUE)


async def change_owner(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    vehicle_id: UUID,
    *,
    expected_version: int,
    client_id: UUID,
) -> None:
    """Cambiar el titular (RF-12): cierra el periodo abierto y abre otro.

    Las órdenes ya abiertas no cambian de cliente: su cliente se copió al
    abrirlas (invariante 7). Se audita (RNF-16) con los ids, no con los nombres.
    """
    # En fila por vehículo: sin el bloqueo, dos cambios a la vez leerían el mismo
    # periodo abierto, y el segundo chocaría con el trigger o con el índice
    # parcial (un 500). Con él, el segundo espera y luego ve otra versión (409).
    vehicle = await vehicle_repo.get_for_update(session, vehicle_id)
    if vehicle is None:
        raise NotFoundError("vehicle_not_found")
    _check_version(vehicle, expected_version)
    await _new_owner(session, client_id)
    current = await vehicle_repo.current_ownership(session, vehicle_id)
    assert current is not None, "un vehículo siempre tiene titular"
    if current.client_id == client_id:
        return

    now = await vehicle_repo.db_now(session)
    # Primero se cierra y se escribe: el periodo nuevo chocaría con el índice de
    # "un solo titular actual" si llegara antes. SQLAlchemy ya emite los UPDATE
    # antes que los INSERT, pero aquí el orden importa y se hace explícito en
    # lugar de depender de eso.
    current.ended_at = now
    await session.flush()
    session.add(
        VehicleOwnership(
            workshop_id=workshop_id,
            vehicle_id=vehicle_id,
            client_id=client_id,
            started_at=now,
        )
    )
    # El titular es parte de lo que se ve en la ficha: tocar el vehículo sube
    # su versión, y quien la tuviera abierta recibe un 409 al guardar encima.
    vehicle.updated_at = now
    session.add(
        AuditEntry(
            workshop_id=workshop_id,
            actor_user_id=user_id,
            action="vehicle_owner_changed",
            target_type="vehicle",
            target_id=vehicle_id,
            details={"client_id": [str(current.client_id), str(client_id)]},
        )
    )
    await session.flush()


async def suggestions(
    session: AsyncSession,
    field: Literal["make", "model"],
    prefix: str,
    make: str | None,
) -> list[str]:
    return await vehicle_repo.suggestions(session, field, prefix.strip(), make, 10)
