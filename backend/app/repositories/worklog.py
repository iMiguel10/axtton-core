"""Diagnóstico, notas internas y trabajos de una orden (RF-22, RF-23)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import DiagnosisVersion, Employee, InternalNote, WorkEntry, WorkOrder


async def current_diagnosis_no(session: AsyncSession, order_id: UUID) -> int:
    """El número de la versión vigente del diagnóstico; 0 si aún no hay."""
    number = await session.scalar(
        select(func.max(DiagnosisVersion.version_no)).where(
            DiagnosisVersion.work_order_id == order_id
        )
    )
    return number or 0


async def diagnosis_versions(
    session: AsyncSession, order_id: UUID
) -> list[tuple[DiagnosisVersion, str]]:
    """Todas las versiones, la vigente primero, con su autor."""
    rows = await session.execute(
        select(DiagnosisVersion, Employee.name)
        .join(Employee, Employee.id == DiagnosisVersion.employee_id)
        .where(DiagnosisVersion.work_order_id == order_id)
        .order_by(DiagnosisVersion.version_no.desc())
    )
    return [(version, name) for version, name in rows]


async def notes(
    session: AsyncSession, order_id: UUID
) -> list[tuple[InternalNote, str]]:
    """El hilo por `seq`, del primero al último, con su autor."""
    rows = await session.execute(
        select(InternalNote, Employee.name)
        .join(Employee, Employee.id == InternalNote.employee_id)
        .where(InternalNote.work_order_id == order_id)
        .order_by(InternalNote.seq)
    )
    return [(note, name) for note, name in rows]


async def work_entries(
    session: AsyncSession, order_id: UUID
) -> list[tuple[WorkEntry, str, str]]:
    """Los trabajos, también los anulados, con quién lo hizo y quién lo anotó."""
    worker = aliased(Employee)
    recorder = aliased(Employee)
    rows = await session.execute(
        select(WorkEntry, worker.name, recorder.name)
        .join(worker, worker.id == WorkEntry.employee_id)
        .join(recorder, recorder.id == WorkEntry.recorded_by_employee_id)
        .where(WorkEntry.work_order_id == order_id)
        .order_by(WorkEntry.worked_on, WorkEntry.created_at)
    )
    return [
        (entry, worker_name, recorder_name)
        for entry, worker_name, recorder_name in rows
    ]


async def count_active_entries(session: AsyncSession, order_id: UUID) -> int:
    """Los trabajos sin anular: los que impiden cancelar (§6)."""
    count = await session.scalar(
        select(func.count()).where(
            WorkEntry.work_order_id == order_id, WorkEntry.voided_at.is_(None)
        )
    )
    return count or 0


async def get_note(session: AsyncSession, note_id: UUID) -> InternalNote | None:
    return await session.get(InternalNote, note_id)


async def get_entry(session: AsyncSession, entry_id: UUID) -> WorkEntry | None:
    return await session.get(WorkEntry, entry_id)


async def get_entry_for_update(
    session: AsyncSession, order_id: UUID, entry_id: UUID
) -> WorkEntry | None:
    query = (
        select(WorkEntry)
        .where(WorkEntry.id == entry_id, WorkEntry.work_order_id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(query)).one_or_none()


async def touch_activity(session: AsyncSession, order_id: UUID, at: datetime) -> None:
    """Un trabajo registrado es actividad (RF-24). Se escribe sin pasar por el
    bloqueo optimista del ORM: `last_activity_at` no lo edita nadie, y subir
    la versión de la orden haría que quien tuviera abierta su recepción
    recibiera un 409 por un trabajo que no toca nada de lo que está editando."""
    await session.execute(
        update(WorkOrder)
        .where(WorkOrder.id == order_id)
        .values(last_activity_at=at)
        .execution_options(synchronize_session=False)
    )
