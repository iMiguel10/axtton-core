from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_email_sender
from app.api.v1 import account
from app.api.v1.deps import Superadmin, require_superadmin
from app.infra.email import EmailSender
from app.platform import audit as platform_audit
from app.platform import workshops as platform_workshops
from app.schemas.admin import (
    WorkshopCreate,
    WorkshopCreated,
    WorkshopRead,
    WorkshopUpdate,
)
from app.schemas.audit import AuditEntryRead, AuditPageRead
from app.schemas.session import WhoAmI

# Toda ruta de este router exige una sesión de superadministrador (A5). Sus
# endpoints solo llaman a app/platform/ y nunca devuelven datos de un taller.
router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_superadmin)],
)
# Las operaciones de cuenta (contraseña, sesiones) heredan la exigencia de actor.
router.include_router(account.router)


@router.get("/me")
async def me(user: Superadmin) -> WhoAmI:
    return WhoAmI(actor=user.actor)


@router.post("/workshops", status_code=status.HTTP_201_CREATED)
async def create_workshop(
    body: WorkshopCreate,
    user: Superadmin,
    email_sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> WorkshopCreated:
    """Alta de un taller e invitación a su primer administrador (RF-112)."""
    created = await platform_workshops.create_workshop(
        name=body.name,
        admin_name=body.admin_name,
        admin_email=str(body.admin_email),
        created_by=user.supertokens_user_id,
        email_sender=email_sender,
    )
    return WorkshopCreated(
        workshop_id=created.workshop_id,
        invitation_email_sent=created.invitation_email_sent,
    )


@router.get("/audit")
async def list_audit(
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditPageRead:
    """Registro de la plataforma (RNF-16): nunca las filas de un taller."""
    rows, next_before = await platform_audit.list_page(before, limit)
    return AuditPageRead(
        entries=[
            AuditEntryRead(
                seq=row.seq,
                created_at=row.created_at,
                action=row.action,
                actor=row.actor_email,
                target_type=row.target_type,
                target_name=row.target_name,
                details=row.details,
            )
            for row in rows
        ],
        next_before=next_before,
    )


@router.get("/workshops")
async def list_workshops() -> list[WorkshopRead]:
    return [
        WorkshopRead(**summary.__dict__)
        for summary in await platform_workshops.list_workshops()
    ]


@router.patch("/workshops/{workshop_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_workshop(
    workshop_id: UUID, body: WorkshopUpdate, user: Superadmin
) -> None:
    """Desactivar o reactivar un taller y ajustar su límite de acceso."""
    await platform_workshops.update_workshop(
        workshop_id,
        status=body.status,
        max_employees_with_access=body.max_employees_with_access,
        updated_by=user.supertokens_user_id,
    )
