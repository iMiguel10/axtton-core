from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import AuditEntry, Employee


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

    Los nombres salen de las fichas de empleados de ESTE taller, también bajo
    RLS: quien actúa es un empleado de aquí, y el objetivo, una ficha de aquí.
    """
    actor = aliased(Employee)
    target = aliased(Employee)
    query = (
        select(AuditEntry, actor.name, target.name)
        .outerjoin(actor, actor.user_id == AuditEntry.actor_user_id)
        .outerjoin(
            target,
            and_(
                AuditEntry.target_type == "employee",
                target.id == AuditEntry.target_id,
            ),
        )
        .order_by(AuditEntry.seq.desc())
        .limit(limit)
    )
    if before_seq is not None:
        query = query.where(AuditEntry.seq < before_seq)
    rows = await session.execute(query)
    return [
        AuditRow(
            seq=entry.seq,
            created_at=entry.created_at,
            action=entry.action,
            actor_name=actor_name,
            target_type=entry.target_type,
            target_name=target_name,
            details=entry.details,
        )
        for entry, actor_name, target_name in rows
    ]
