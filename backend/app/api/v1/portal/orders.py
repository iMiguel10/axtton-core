from uuid import UUID

from fastapi import APIRouter

from app.api.v1.portal.deps import Portal
from app.schemas.portal import PortalOrderDetail, PortalVehicle
from app.services import portal_orders as portal_orders_service

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
