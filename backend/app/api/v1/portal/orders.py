from uuid import UUID

from fastapi import APIRouter, Request, status

from app.api.rate_limit import request_ip
from app.api.v1.portal.deps import Portal
from app.schemas.portal import (
    PortalDecisionCreate,
    PortalOrderDetail,
    PortalVehicle,
)
from app.services import portal_orders as portal_orders_service
from app.services import quotes as quote_service

# El cliente sale siempre de la sesión: ninguna ruta lo recibe (T4, T10).
router = APIRouter()


@router.get("/vehicles")
async def vehicles(portal: Portal) -> list[PortalVehicle]:
    found = await portal_orders_service.vehicles_of(portal.session, portal.client_id)
    return [PortalVehicle.model_validate(vehicle) for vehicle in found]


@router.get("/orders/{order_id}")
async def order(order_id: UUID, portal: Portal) -> PortalOrderDetail:
    detail = await portal_orders_service.order_detail(
        portal.session,
        portal.client_id,
        order_id,
        timezone=portal.client.timezone,
    )
    return PortalOrderDetail.model_validate(detail)


@router.post("/quotes/{quote_id}/decision", status_code=status.HTTP_204_NO_CONTENT)
async def decide_quote(
    quote_id: UUID, body: PortalDecisionCreate, portal: Portal, request: Request
) -> None:
    await quote_service.decide_from_portal(
        portal.session,
        portal.workshop_id,
        portal.client_id,
        quote_id,
        outcome=body.outcome,
        reason=body.reason,
        ip=request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
