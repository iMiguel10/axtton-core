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
    """Solo datos de cuenta y recuentos: nada operativo del taller (RNF-08)."""

    id: UUID
    name: str
    status: str
    created_at: datetime
    max_employees_with_access: int
    employees_with_access: int
    pending_invitations: int


class WorkshopUpdate(BaseModel):
    status: Literal["active", "inactive"] | None = None
    max_employees_with_access: int | None = Field(default=None, ge=1, le=1000)
