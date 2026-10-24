"""Registro de auditoría del taller activo (RNF-16). Solo para quien puede verlo."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.v1.workshop.deps import WorkshopContext, require
from app.domain.permissions import Action
from app.schemas.audit import AuditEntryRead, AuditPageRead
from app.services import audit as audit_service

router = APIRouter(prefix="/audit")

Auditor = Annotated[WorkshopContext, Depends(require(Action.VIEW_AUDIT_LOG))]


@router.get("")
async def list_audit(
    workshop: Auditor,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditPageRead:
    page = await audit_service.list_entries(workshop.session, before, limit)
    return AuditPageRead(
        entries=[
            AuditEntryRead(
                seq=row.seq,
                created_at=row.created_at,
                action=row.action,
                actor=row.actor_name,
                target_type=row.target_type,
                target_name=row.target_name,
                details=row.details,
            )
            for row in page.entries
        ],
        next_before=page.next_before,
    )
