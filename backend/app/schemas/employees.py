from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.domain.permissions import Role


class EmployeeRead(BaseModel):
    id: UUID
    name: str
    position: str | None
    role: Role
    active: bool
    has_access: bool
    invitation_pending: bool
    # Nulo si quien consulta no puede ver costes.
    hourly_cost_cents: int | None
    # El cliente la devuelve al editar: es el bloqueo optimista (RNF-15).
    version: int


class EmployeeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    position: str | None = Field(default=None, max_length=100)
    role: Role
    hourly_cost_cents: int | None = Field(default=None, ge=0)


class EmployeeCreated(BaseModel):
    id: UUID


class EmployeeUpdate(BaseModel):
    """Solo los campos presentes se cambian (exclude_unset al usarlo)."""

    version: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    position: str | None = Field(default=None, max_length=100)
    role: Role | None = None
    active: bool | None = None
    hourly_cost_cents: int | None = Field(default=None, ge=0)


class VersionOnly(BaseModel):
    version: int


class InvitationCreate(BaseModel):
    email: EmailStr


class InvitationQueued(BaseModel):
    # El email sale después del commit; si no hay SMTP, no sale (RNF-32).
    invitation_email_queued: bool
