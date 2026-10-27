"""Los límites del taller activo y lo gastado de cada uno (especificación §10).

Los ve su administrador, para saber cuánto le queda antes de llegar al tope; los
cambia solo el superadministrador (/admin).
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.v1.workshop.deps import WorkshopContext, require
from app.domain.permissions import Action
from app.schemas.limits import LimitUsage
from app.services import limits as limit_service

router = APIRouter(prefix="/limits")

Viewer = Annotated[WorkshopContext, Depends(require(Action.VIEW_LIMITS))]


@router.get("")
async def workshop_limits(workshop: Viewer) -> list[LimitUsage]:
    report = await limit_service.usage_report(workshop.session, workshop.workshop_id)
    return [
        LimitUsage(resource=usage.resource, used=usage.used, limit=usage.limit)
        for usage in report
    ]
