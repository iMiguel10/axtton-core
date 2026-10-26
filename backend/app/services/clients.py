"""Clientes del taller activo (RF-10).

Todo se ejecuta en la transacción del taller activo (RLS fijada): un cliente de
otro taller no existe y responde 404 (RNF-01). Los clientes no se auditan al
crearlos o editarlos: no está entre las acciones sensibles de RNF-16, y el
registro guardaría datos personales sin necesitarlos.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.domain.clients import normalize_email, normalize_tax_id
from app.models import Client
from app.repositories import clients as client_repo

# Campos que se pueden cambiar con PATCH. Archivar tiene sus propias operaciones.
EDITABLE = ("kind", "name", "tax_id", "phone", "email", "address", "notes", "language")

EMAIL_INDEX = "uq_clients_workshop_id_email"


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


def _check_version(client: Client, expected: int) -> None:
    """Bloqueo optimista a nivel HTTP (RNF-15), como en los empleados."""
    if client.version != expected:
        raise ConflictError("modified_by_someone_else")


async def _flush_checking_email(session: AsyncSession) -> None:
    """La comprobación previa de `email_taken` da el error amable; esta es la que
    vale cuando dos personas guardan el mismo email a la vez: las dos pasan la
    comprobación, y el índice único rechaza a la segunda. Sin traducirlo, sería
    un 500."""
    try:
        await session.flush()
    except IntegrityError as error:
        if EMAIL_INDEX in str(error.orig):
            raise ConflictError("client_email_taken") from error
        raise


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
    values = _normalized(fields)
    if values.get("email") and await client_repo.email_taken(session, values["email"]):
        raise ConflictError("client_email_taken")
    client = Client(workshop_id=workshop_id, **values)
    session.add(client)
    await _flush_checking_email(session)
    return client.id


async def update_client(
    session: AsyncSession,
    client_id: UUID,
    *,
    expected_version: int,
    changes: dict[str, Any],
) -> None:
    client = await _get(session, client_id)
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
    await _flush_checking_email(session)


async def set_archived(
    session: AsyncSession, client_id: UUID, *, expected_version: int, archived: bool
) -> None:
    """Archivar lo saca de los listados, sin borrar nada (RF-10). Desarchivar lo
    devuelve tal cual estaba."""
    client = await _get(session, client_id)
    _check_version(client, expected_version)
    if (client.archived_at is not None) == archived:
        return
    client.archived_at = datetime.now(UTC) if archived else None
    await session.flush()
