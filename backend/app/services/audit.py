"""Consulta del registro de auditoría del taller (RNF-16)."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import audit as audit_repo
from app.repositories.audit import AuditRow


@dataclass(frozen=True)
class AuditPage:
    entries: list[AuditRow]
    # Para pedir la página siguiente (las anteriores en el tiempo); None si no hay.
    next_before: int | None


async def list_entries(
    session: AsyncSession, before_seq: int | None, limit: int
) -> AuditPage:
    # Se pide una fila de más: si llega, hay otra página.
    rows = await audit_repo.list_page(session, before_seq, limit + 1)
    entries = rows[:limit]
    more = len(rows) > limit
    return AuditPage(entries, entries[-1].seq if more else None)
