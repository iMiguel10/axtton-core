"""Clientes del taller activo (RF-10).

Todo se ejecuta en la transacción del taller activo (RLS fijada): un cliente de
otro taller no existe y responde 404 (RNF-01). Los clientes no se auditan al
crearlos o editarlos: no está entre las acciones sensibles de RNF-16, y el
registro guardaría datos personales sin necesitarlos.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.domain.clients import normalize_email, normalize_tax_id
from app.domain.limits import Resource
from app.models import AuditEntry, Client
from app.repositories import clients as client_repo
from app.repositories import vehicles as vehicle_repo
from app.repositories import work_orders as order_repo
from app.services import limits as limit_service
from app.services.integrity import flush_or_conflict

# Campos que se pueden cambiar con PATCH. Archivar tiene sus propias operaciones.
EDITABLE = ("kind", "name", "tax_id", "phone", "email", "address", "notes", "language")

# Si dos guardan el mismo email a la vez, el índice único para al segundo.
UNIQUE = {"uq_clients_workshop_id_email": "client_email_taken"}


OPTIONAL_TEXT = ("tax_id", "address", "notes")


def _normalized(changes: dict[str, Any]) -> dict[str, Any]:
    result = dict(changes)
    # Un campo opcional vacío es "no lo sé", no un texto: se guarda nulo.
    for field in OPTIONAL_TEXT:
        if field in result and not result[field]:
            result[field] = None
    if result.get("email") is not None:
        result["email"] = normalize_email(result["email"])
    if result.get("tax_id") is not None:
        result["tax_id"] = normalize_tax_id(result["tax_id"]) or None
    return result


async def _get(session: AsyncSession, client_id: UUID) -> Client:
    client = await client_repo.get(session, client_id)
    if client is None:
        raise NotFoundError("client_not_found")
    return client


async def _get_editable(session: AsyncSession, client_id: UUID) -> Client:
    """Un anonimizado no se edita ni se desarchiva (RF-15: es irreversible). El
    trigger clients_anonymized_frozen lo impide igual; esto da el 409."""
    client = await _get(session, client_id)
    if client.anonymized_at is not None:
        raise ConflictError("client_anonymized")
    return client


def _check_version(client: Client, expected: int) -> None:
    """Bloqueo optimista a nivel HTTP (RNF-15), como en los empleados."""
    if client.version != expected:
        raise ConflictError("modified_by_someone_else")


async def list_clients(
    session: AsyncSession,
    *,
    query: str | None,
    archived: bool,
    limit: int,
    offset: int,
) -> list[Client]:
    return await client_repo.list_page(
        session,
        query=query.strip() if query else None,
        archived=archived,
        limit=limit,
        offset=offset,
    )


async def get_client(session: AsyncSession, client_id: UUID) -> Client:
    return await _get(session, client_id)


async def create_client(
    session: AsyncSession, workshop_id: UUID, fields: dict[str, Any]
) -> UUID:
    # Primero el límite (§10): es el primer bloqueo de toda alta.
    await limit_service.ensure_room(session, workshop_id, Resource.CLIENTS)
    values = _normalized(fields)
    if values.get("email") and await client_repo.email_taken(session, values["email"]):
        raise ConflictError("client_email_taken")
    client = Client(workshop_id=workshop_id, **values)
    session.add(client)
    await flush_or_conflict(session, UNIQUE)
    return client.id


async def update_client(
    session: AsyncSession,
    client_id: UUID,
    *,
    expected_version: int,
    changes: dict[str, Any],
) -> None:
    client = await _get_editable(session, client_id)
    _check_version(client, expected_version)
    values = _normalized(changes)
    email = values.get("email")
    if (
        email
        and email != client.email
        and await client_repo.email_taken(session, email, except_id=client_id)
    ):
        raise ConflictError("client_email_taken")
    for field in EDITABLE:
        if field in values:
            setattr(client, field, values[field])
    await flush_or_conflict(session, UNIQUE)


async def set_archived(
    session: AsyncSession, client_id: UUID, *, expected_version: int, archived: bool
) -> None:
    """Archivar lo saca de los listados, sin borrar nada (RF-10). Desarchivar lo
    devuelve tal cual estaba."""
    client = await _get_editable(session, client_id)
    _check_version(client, expected_version)
    if (client.archived_at is not None) == archived:
        return
    client.archived_at = datetime.now(UTC) if archived else None
    await session.flush()


# Lo que queda de un cliente anonimizado: la fila, su tipo y su idioma, sin un
# solo dato personal. El CHECK ck_clients_anonymized_empty exige exactamente esto.
ANONYMIZED = {
    "name": "",
    "phone": "",
    "email": None,
    "tax_id": None,
    "address": None,
    "notes": None,
}


async def anonymize_client(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    client_id: UUID,
    *,
    expected_version: int,
) -> None:
    """Borrar a un cliente que lo pide (RF-15, RNF-40): se vacían sus datos
    personales y se conserva la fila, con sus órdenes y vehículos ligados a un
    "cliente eliminado". Es irreversible y queda en la auditoría.

    Con alguna orden abierta no se puede: esa orden aún necesita a quién avisar.
    """
    # Exclusivo y antes de contar: abrir una orden pide el compartido, así que
    # una apertura a la vez espera, y luego ve al cliente anonimizado.
    client = await client_repo.get_locked(session, client_id, shared=False)
    if client is None:
        raise NotFoundError("client_not_found")
    if client.anonymized_at is not None:
        raise ConflictError("client_anonymized")
    _check_version(client, expected_version)
    if await order_repo.count_open_for_client(session, client_id):
        raise ConflictError("client_has_open_orders")

    now = await vehicle_repo.db_now(session)
    for field, value in ANONYMIZED.items():
        setattr(client, field, value)
    client.archived_at = client.archived_at or now
    client.anonymized_at = now
    await order_repo.forget_dropped_off_by(session, client_id)
    session.add(
        AuditEntry(
            workshop_id=workshop_id,
            actor_user_id=user_id,
            action="client_anonymized",
            target_type="client",
            # Solo el id: el nombre ya no existe en ninguna parte (RF-15).
            target_id=client_id,
            details={},
        )
    )
    await session.flush()
