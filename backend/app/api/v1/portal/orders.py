from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from app.api.rate_limit import limit_portal_pdf, request_ip
from app.api.v1.portal.deps import Portal
from app.schemas.portal import (
    PortalDecisionCreate,
    PortalOrderDetail,
    PortalVehicle,
)
from app.services import portal_orders as portal_orders_service
from app.services import quote_pdf as quote_pdf_service
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


@router.get("/quotes/{quote_id}/pdf")
async def quote_pdf(quote_id: UUID, portal: Portal) -> Response:
    """El PDF de una versión enviada (RF-54). Se genera ahora y no se guarda, y
    solo lo descarga la sesión de su cliente: no hay enlace público."""
    await limit_portal_pdf(portal.workshop_id, portal.client_id)
    pdf = await quote_pdf_service.client_quote_pdf(
        portal.session, portal.workshop_id, portal.client_id, quote_id
    )
    return Response(
        content=pdf.content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{pdf.filename}"',
            # La sesión va por cookie: que ningún proxy lo guarde para otro.
            "Cache-Control": "private, no-store",
        },
    )


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
