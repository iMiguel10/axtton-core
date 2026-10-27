"""Diagnóstico, notas internas y trabajos de una orden (RF-22, RF-23, RF-25).

Los lee y los escribe todo el personal (especificación §3).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.v1.workshop.deps import WorkshopContext, require
from app.domain.permissions import Action
from app.schemas.worklog import (
    DiagnosisSave,
    DiagnosisSaved,
    DiagnosisVersionRead,
    NoteCreate,
    NoteRead,
    WorkEntryCreate,
    WorkEntryCreated,
    WorkEntryRead,
    Worker,
    WorklogRead,
)
from app.services import worklog as worklog_service

router = APIRouter(prefix="/orders/{order_id}")

Viewer = Annotated[WorkshopContext, Depends(require(Action.VIEW_ORDERS))]
Writer = Annotated[WorkshopContext, Depends(require(Action.WRITE_WORKLOG))]


@router.get("/worklog")
async def get_worklog(order_id: UUID, workshop: Viewer) -> WorklogRead:
    log = await worklog_service.worklog(
        workshop.session, order_id, workshop.employee_id, workshop.role
    )
    return WorklogRead(
        diagnosis=[
            DiagnosisVersionRead(
                version_no=version.version_no,
                text=version.text,
                employee_name=name,
                created_at=version.created_at,
            )
            for version, name in log.diagnosis
        ],
        notes=[
            NoteRead(
                seq=note.seq,
                body=note.body,
                employee_name=name,
                created_at=note.created_at,
            )
            for note, name in log.notes
        ],
        work_entries=[
            WorkEntryRead(
                id=view.entry.id,
                employee=Worker(id=view.entry.employee_id, name=view.worker_name),
                recorded_by_name=view.recorder_name,
                description=view.entry.description,
                worked_on=view.entry.worked_on,
                hours=view.entry.hours,
                voided_at=view.entry.voided_at,
                can_void=view.can_void,
            )
            for view in log.entries
        ],
        workers=log.workers,
    )


@router.post("/diagnosis", status_code=status.HTTP_201_CREATED)
async def save_diagnosis(
    order_id: UUID, body: DiagnosisSave, workshop: Writer
) -> DiagnosisSaved:
    version_no = await worklog_service.save_diagnosis(
        workshop.session,
        workshop.workshop_id,
        workshop.employee_id,
        order_id,
        base_version_no=body.base_version_no,
        text=body.text,
    )
    return DiagnosisSaved(version_no=version_no)


@router.post("/notes", status_code=status.HTTP_201_CREATED)
async def add_note(order_id: UUID, body: NoteCreate, workshop: Writer) -> None:
    await worklog_service.add_note(
        workshop.session,
        workshop.workshop_id,
        workshop.employee_id,
        order_id,
        note_id=body.id,
        body=body.body,
    )


@router.post("/work-entries", status_code=status.HTTP_201_CREATED)
async def add_work_entry(
    order_id: UUID, body: WorkEntryCreate, workshop: Writer
) -> WorkEntryCreated:
    entry_id = await worklog_service.add_work_entry(
        workshop.session,
        workshop.workshop_id,
        workshop.employee_id,
        order_id,
        entry_id=body.id,
        employee_id=body.employee_id,
        description=body.description,
        worked_on=body.worked_on,
        hours=body.hours,
    )
    return WorkEntryCreated(id=entry_id)


@router.post("/work-entries/{entry_id}/void", status_code=status.HTTP_204_NO_CONTENT)
async def void_work_entry(order_id: UUID, entry_id: UUID, workshop: Writer) -> None:
    await worklog_service.void_work_entry(
        workshop.session, workshop.employee_id, workshop.role, order_id, entry_id
    )
