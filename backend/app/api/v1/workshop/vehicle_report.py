"""El informe de actuaciones de un vehículo (F6 paso 5, RF-18).

Lo genera todo el personal. Con los titulares o los importes (`owners`,
`amounts`), solo el administrador, y queda en la auditoría (RNF-16): el service
lo comprueba y lo anota.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.responses import pdf_response
from app.api.v1.workshop.deps import WorkshopContext, require
from app.domain.permissions import Action
from app.services import vehicle_report as report_service

router = APIRouter(prefix="/vehicles/{vehicle_id}/report")

Viewer = Annotated[WorkshopContext, Depends(require(Action.VIEW_ORDERS))]


@router.get("/pdf")
async def vehicle_report_pdf(
    vehicle_id: UUID, workshop: Viewer, owners: bool = False, amounts: bool = False
) -> Response:
    """Todas las órdenes del vehículo, de cualquier titular (RF-18). Sin los
    titulares ni los importes salvo que el administrador los pida. Se genera
    ahora y no se guarda (A14)."""
    pdf = await report_service.vehicle_report_pdf(
        workshop.session,
        workshop.workshop_id,
        workshop.user_id,
        workshop.role,
        vehicle_id,
        owners=owners,
        amounts=amounts,
    )
    return pdf_response(pdf.content, pdf.filename)
