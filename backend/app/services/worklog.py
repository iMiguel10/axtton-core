"""Diagnóstico, notas internas y trabajos de una orden (RF-22, RF-23, RF-25).

Lo escribe todo el personal (Action.WRITE_WORKLOG). Una orden cerrada solo
admite notas (RF-26). Nada de esto se reescribe: el diagnóstico se versiona, las
notas se añaden y un trabajo mal anotado se anula.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.domain.permissions import Action, can
from app.domain.work_orders import CLOSED
from app.models import DiagnosisVersion, InternalNote, WorkEntry, WorkOrder
from app.repositories import employees as employee_repo
from app.repositories import vehicles as vehicle_repo
from app.repositories import work_orders as order_repo
from app.repositories import worklog as worklog_repo
from app.services.integrity import flush_or_conflict

# Dos que guardan el diagnóstico desde la misma versión escriben la misma
# siguiente: el índice único para al segundo (RNF-15).
DIAGNOSIS_UNIQUE = {
    "uq_diagnosis_versions_work_order_id_version_no": "modified_by_someone_else"
}


@dataclass(frozen=True)
class EntryView:
    entry: WorkEntry
    worker_name: str
    recorder_name: str
    # Si quien consulta lo puede anular: lo anotó él, o gestiona órdenes.
    can_void: bool


@dataclass(frozen=True)
class Worklog:
    diagnosis: list[tuple[DiagnosisVersion, str]]
    notes: list[tuple[InternalNote, str]]
    entries: list[EntryView]

    @property
    def workers(self) -> list[str]:
        """Los mecánicos que han trabajado en la orden (RF-25): salen de los
        trabajos sin anular, así que nunca se desincronizan de lo hecho."""
        return sorted(
            {e.worker_name for e in self.entries if e.entry.voided_at is None}
        )


def _check_open(order: WorkOrder | None) -> WorkOrder:
    if order is None:
        raise NotFoundError("work_order_not_found")
    if order.status in CLOSED:
        raise ConflictError("work_order_closed")
    return order


def _can_void(entry: WorkEntry, employee_id: UUID, role: str) -> bool:
    return entry.voided_at is None and (
        entry.recorded_by_employee_id == employee_id or can(role, Action.MANAGE_ORDERS)
    )


async def worklog(
    session: AsyncSession, order_id: UUID, employee_id: UUID, role: str
) -> Worklog:
    if await order_repo.get(session, order_id) is None:
        raise NotFoundError("work_order_not_found")
    entries = await worklog_repo.work_entries(session, order_id)
    return Worklog(
        diagnosis=await worklog_repo.diagnosis_versions(session, order_id),
        notes=await worklog_repo.notes(session, order_id),
        entries=[
            EntryView(entry, worker, recorder, _can_void(entry, employee_id, role))
            for entry, worker, recorder in entries
        ],
    )


async def save_diagnosis(
    session: AsyncSession,
    workshop_id: UUID,
    employee_id: UUID,
    order_id: UUID,
    *,
    base_version_no: int,
    text: str,
) -> int:
    """Guarda una versión nueva del texto para el cliente (RF-22).

    `base_version_no` es la versión desde la que se editó (0 si no había): si
    entretanto otra persona guardó otra, es un 409 y no se pisa (RNF-15).
    """
    _check_open(await order_repo.get_for_share(session, order_id))
    current = await worklog_repo.current_diagnosis_no(session, order_id)
    if current != base_version_no:
        raise ConflictError("modified_by_someone_else")
    session.add(
        DiagnosisVersion(
            workshop_id=workshop_id,
            work_order_id=order_id,
            version_no=current + 1,
            text=text,
            employee_id=employee_id,
        )
    )
    await flush_or_conflict(session, DIAGNOSIS_UNIQUE)
    return current + 1


async def add_note(
    session: AsyncSession,
    workshop_id: UUID,
    employee_id: UUID,
    order_id: UUID,
    *,
    body: str,
) -> None:
    """Añade una entrada al hilo de notas internas (RF-22). También con la
    orden cerrada: es lo único que admite, además del cobro (RF-26)."""
    if await order_repo.get(session, order_id) is None:
        raise NotFoundError("work_order_not_found")
    session.add(
        InternalNote(
            workshop_id=workshop_id,
            work_order_id=order_id,
            employee_id=employee_id,
            body=body,
        )
    )
    await session.flush()


async def add_work_entry(
    session: AsyncSession,
    workshop_id: UUID,
    recorder_id: UUID,
    order_id: UUID,
    *,
    employee_id: UUID,
    description: str,
    worked_on: date,
    hours: Decimal | None,
) -> UUID:
    """Registra un trabajo (RF-23): quién lo hizo, aunque lo anote otro."""
    # FOR NO KEY UPDATE, no FOR SHARE: aquí también se actualiza la orden
    # (repositories/work_orders.py::get_for_activity).
    _check_open(await order_repo.get_for_activity(session, order_id))
    worker = await employee_repo.get(session, employee_id)
    if worker is None or not worker.active:
        raise NotFoundError("employee_not_found")
    entry = WorkEntry(
        workshop_id=workshop_id,
        work_order_id=order_id,
        employee_id=employee_id,
        recorded_by_employee_id=recorder_id,
        description=description,
        worked_on=worked_on,
        hours=hours,
    )
    session.add(entry)
    await session.flush()
    await worklog_repo.touch_activity(
        session, order_id, await vehicle_repo.db_now(session)
    )
    return entry.id


async def void_work_entry(
    session: AsyncSession,
    employee_id: UUID,
    role: str,
    order_id: UUID,
    entry_id: UUID,
) -> None:
    """Anula un trabajo mal anotado. Lo puede anular quien lo anotó o quien
    gestiona órdenes; nadie más toca lo que anotó otro (RF-22)."""
    _check_open(await order_repo.get_for_share(session, order_id))
    entry = await worklog_repo.get_entry_for_update(session, order_id, entry_id)
    if entry is None:
        raise NotFoundError("work_entry_not_found")
    if entry.recorded_by_employee_id != employee_id and not can(
        role, Action.MANAGE_ORDERS
    ):
        raise ForbiddenError("not_allowed")
    if entry.voided_at is not None:
        raise ConflictError("work_entry_already_voided")
    entry.voided_at = await vehicle_repo.db_now(session)
    entry.voided_by_employee_id = employee_id
    await session.flush()
