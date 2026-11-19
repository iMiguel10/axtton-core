"""El resumen de entrega de una orden (F6 paso 4, RF-53).

Lo descarga todo el personal, salvo quien no ve importes (el mecánico, si el
taller lo desactiva): lleva el del presupuesto aprobado, como el PDF del
presupuesto.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.responses import pdf_response
from app.api.v1.workshop.deps import WorkshopContext, require
from app.domain.permissions import Action
from app.services import delivery_summary as delivery_service

router = APIRouter(prefix="/orders/{order_id}/delivery-summary")

Viewer = Annotated[WorkshopContext, Depends(require(Action.VIEW_ORDERS))]


@router.get("/pdf")
async def delivery_summary_pdf(order_id: UUID, workshop: Viewer) -> Response:
    """De una orden entregada: sus trabajos, piezas, km, el importe aprobado y la
    garantía (RF-53). Sale igual cada vez (RF-55); se genera ahora y no se
    guarda (A14)."""
    pdf = await delivery_service.delivery_summary_pdf(
        workshop.session, workshop.workshop_id, workshop.role, order_id
    )
    return pdf_response(pdf.content, pdf.filename)
