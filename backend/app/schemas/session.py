from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.domain.actors import Actor


class WhoAmI(BaseModel):
    actor: Actor


class WorkshopMembership(BaseModel):
    workshop_id: UUID
    workshop_name: str
    # IANA ("Europe/Madrid"): las fechas se enseñan en la del taller, no en la
    # del navegador.
    timezone: str
    role: str


class StaffMe(WhoAmI):
    workshops: list[WorkshopMembership]


class ActiveWorkshopRead(BaseModel):
    workshop_id: UUID
    employee_id: UUID
    role: str


class AdminMe(WhoAmI):
    # Taller único (RF-111): la interfaz oculta el alta cuando ya hay un taller.
    installation_mode: Literal["multi", "single"]
