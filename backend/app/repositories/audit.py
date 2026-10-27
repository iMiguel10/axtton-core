from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, String, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import AuditEntry, Client, Employee, Vehicle, WorkOrder


@dataclass(frozen=True)
class AuditRow:
    seq: int
    created_at: datetime
    action: str
    actor_name: str | None
    target_type: str | None
    target_name: str | None
    details: dict[str, Any]


async def list_page(
    session: AsyncSession, before_seq: int | None, limit: int
) -> list[AuditRow]:
    """Registro del taller fijado, del más reciente al más antiguo.

    Bajo RLS: solo filas de este taller; las de plataforma (workshop_id nulo)
    no entran en ningún conjunto de talleres. Ordenado y paginado por `seq`,
    nunca por fecha (dos filas pueden compartir instante).

    Los nombres salen de las fichas de ESTE taller, también bajo RLS: quien
    actúa es un empleado de aquí, y el objetivo, una ficha o un vehículo de aquí.

    De los clientes, el registro guarda solo el id (RNF-16 con datos mínimos):
    su nombre se pone al leer. Así, anonimizar a un cliente (RF-15) lo borra
    también de aquí, sin tocar una tabla append-only.
    """
    actor = aliased(Employee)
    target = aliased(Employee)
    query = (
        select(
            AuditEntry,
            actor.name,
            target.name,
            Vehicle.plate,
            _order_code(),
            Client.name,
        )
        .outerjoin(actor, actor.user_id == AuditEntry.actor_user_id)
        .outerjoin(
            target,
            and_(
                AuditEntry.target_type == "employee",
                target.id == AuditEntry.target_id,
            ),
        )
        .outerjoin(
            Vehicle,
            and_(
                AuditEntry.target_type == "vehicle",
                Vehicle.id == AuditEntry.target_id,
            ),
        )
        .outerjoin(
            WorkOrder,
            and_(
                AuditEntry.target_type == "work_order",
                WorkOrder.id == AuditEntry.target_id,
            ),
        )
        # Un cliente anonimizado tiene el nombre vacío: la interfaz lo enseña
        # como "cliente eliminado".
        .outerjoin(
            Client,
            and_(
                AuditEntry.target_type == "client",
                Client.id == AuditEntry.target_id,
            ),
        )
        .order_by(AuditEntry.seq.desc())
        .limit(limit)
    )
    if before_seq is not None:
        query = query.where(AuditEntry.seq < before_seq)
    rows = (await session.execute(query)).all()
    client_names = await _client_names(session, [entry for entry, *_ in rows])
    return [
        AuditRow(
            seq=entry.seq,
            created_at=entry.created_at,
            action=entry.action,
            actor_name=actor_name,
            target_type=entry.target_type,
            target_name=(
                client_name
                if entry.target_type == "client"
                else employee_name or plate or order_code
            ),
            details=_with_client_names(entry.details, client_names),
        )
        for entry, actor_name, employee_name, plate, order_code, client_name in rows
    ]


def _client_ids(details: dict[str, Any]) -> list[str]:
    value = details.get("client_id")
    return [str(v) for v in value if v] if isinstance(value, list) else []


async def _client_names(
    session: AsyncSession, entries: list[AuditEntry]
) -> dict[str, str]:
    ids = {UUID(i) for entry in entries for i in _client_ids(entry.details)}
    if not ids:
        return {}
    rows = await session.execute(
        select(Client.id, Client.name).where(Client.id.in_(ids))
    )
    return {str(client_id): name for client_id, name in rows}


def _with_client_names(
    details: dict[str, Any], names: dict[str, str]
) -> dict[str, Any]:
    if not _client_ids(details):
        return details
    return {**details, "client_id": [names.get(i, i) for i in details["client_id"]]}


def _order_code() -> ColumnElement[str | None]:
    """OT-2026-0042, como domain.order_code, pero en SQL para el join. Nulo si
    la fila no es de una orden (concat ignoraría los nulos y daría "OT--")."""
    code = func.concat(
        "OT-",
        WorkOrder.year,
        "-",
        func.lpad(cast(WorkOrder.number, String), 4, "0"),
    )
    return case((WorkOrder.id.is_not(None), code), else_=None)
