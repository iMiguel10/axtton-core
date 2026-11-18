"""La hoja de recepción de una orden (F6, RF-51, RF-52).

Generarla, firmarla en pantalla o marcarla firmada en papel es del administrador
(especificación §3). Cómo se firmó viene en la ficha de la orden.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.responses import pdf_response
from app.api.v1.workshop.deps import WorkshopContext, require
from app.domain.permissions import Action
from app.schemas.reception import SignReception
from app.services import reception as reception_service
from app.services import reception_pdf as reception_pdf_service

router = APIRouter(prefix="/orders/{order_id}/reception-sheet")

Signer = Annotated[WorkshopContext, Depends(require(Action.SIGN_RECEPTION))]


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def sign_reception(order_id: UUID, body: SignReception, workshop: Signer) -> None:
    await reception_service.sign(
        workshop.session,
        workshop.workshop_id,
        workshop.employee_id,
        workshop.user_id,
        order_id,
        expected_version=body.version,
        method=body.method,
        signer_name=body.signer_name,
        signature=(
            reception_service.ScreenSignature(
                width=body.signature.width,
                height=body.signature.height,
                strokes=body.signature.strokes,
            )
            if body.signature
            else None
        ),
    )


@router.get("/pdf")
async def reception_pdf(order_id: UUID, workshop: Signer) -> Response:
    """La hoja en PDF (RF-51): firmada, desde su copia congelada, idéntica cada
    vez (RF-55); sin firmar, con los datos de la orden, para imprimirla y
    firmarla en papel. Se genera ahora y no se guarda (A14)."""
    pdf = await reception_pdf_service.reception_pdf(
        workshop.session, workshop.workshop_id, order_id, for_client=False
    )
    return pdf_response(pdf.content, pdf.filename)
