"""Registro de auditoría de la plataforma (RNF-16), para el superadministrador.

Solo las filas de plataforma, las de `workshop_id` nulo: alta y cambios de
talleres, alta de superadministradores. Las de cada taller no salen nunca de
aquí, aunque el rol de plataforma pueda leerlas (RNF-08: nada operativo).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select

from app.infra import identity
from app.models import AuditEntry, User, Workshop
from app.platform.db import platform_transaction


@dataclass(frozen=True)
class PlatformAuditRow:
    seq: int
    created_at: datetime
    action: str
    actor_email: str | None
    target_type: str | None
    target_name: str | None
    details: dict[str, Any]


async def list_page(
    before_seq: int | None, limit: int
) -> tuple[list[PlatformAuditRow], int | None]:
    query = (
        select(AuditEntry, User.supertokens_user_id, Workshop.name)
        .outerjoin(User, User.id == AuditEntry.actor_user_id)
        .outerjoin(
            Workshop,
            and_(
                AuditEntry.target_type == "workshop",
                Workshop.id == AuditEntry.target_id,
            ),
        )
        .where(AuditEntry.workshop_id.is_(None))
        .order_by(AuditEntry.seq.desc())
        .limit(limit + 1)
    )
    if before_seq is not None:
        query = query.where(AuditEntry.seq < before_seq)
    async with platform_transaction() as session:
        # Se pide una fila de más: si llega, hay otra página.
        rows = list((await session.execute(query)).all())

    more = len(rows) > limit
    rows = rows[:limit]
    # El email vive en SuperTokens, no en nuestra base: uno por superadministrador
    # distinto de la página, no uno por fila.
    emails: dict[str, str] = {}
    for _, supertokens_user_id, _ in rows:
        if supertokens_user_id and supertokens_user_id not in emails:
            emails[supertokens_user_id] = await identity.email_of(supertokens_user_id)
    entries = [
        PlatformAuditRow(
            seq=entry.seq,
            created_at=entry.created_at,
            action=entry.action,
            actor_email=emails.get(supertokens_user_id or ""),
            target_type=entry.target_type,
            target_name=workshop_name,
            details=entry.details,
        )
        for entry, supertokens_user_id, workshop_name in rows
    ]
    return entries, entries[-1].seq if more else None
