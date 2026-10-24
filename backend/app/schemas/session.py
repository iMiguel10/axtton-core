from uuid import UUID

from pydantic import BaseModel

from app.domain.actors import Actor


class WhoAmI(BaseModel):
    actor: Actor


class WorkshopMembership(BaseModel):
    workshop_id: UUID
    workshop_name: str
    role: str


class StaffMe(WhoAmI):
    workshops: list[WorkshopMembership]


class ActiveWorkshopRead(BaseModel):
    workshop_id: UUID
    employee_id: UUID
    role: str
