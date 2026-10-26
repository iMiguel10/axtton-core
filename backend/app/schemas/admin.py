from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class WorkshopCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    admin_name: str = Field(min_length=1, max_length=200)
    admin_email: EmailStr


class WorkshopCreated(BaseModel):
    workshop_id: UUID
    # False si no hay SMTP configurado (RNF-32): la invitación existe igual.
    invitation_email_sent: bool


class WorkshopRead(BaseModel):
    """Datos de cuenta, administradores y recuentos: nada operativo (RNF-08)."""

    id: UUID
    name: str
    status: str
    created_at: datetime
    max_employees_with_access: int
    employees_with_access: int
    pending_invitations: int
    # Nombres de los administradores activos (RF-114), sin email.
    admins: list[str]


class WorkshopUpdate(BaseModel):
    status: Literal["active", "inactive"] | None = None
    max_employees_with_access: int | None = Field(default=None, ge=1, le=1000)


class SuperadminInvitationCreate(BaseModel):
    email: EmailStr


class SuperadminInvitationSent(BaseModel):
    # False si no hay SMTP configurado (RNF-32): la invitación existe igual.
    invitation_email_sent: bool


class SuperadminRead(BaseModel):
    email: str
    created_at: datetime


class PendingSuperadminInvitation(BaseModel):
    id: UUID
    email: str
    expires_at: datetime


class SuperadminsRead(BaseModel):
    superadmins: list[SuperadminRead]
    pending_invitations: list[PendingSuperadminInvitation]
