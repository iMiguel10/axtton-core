from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from app.api.responses import pdf_response
from app.api.v1.workshop.deps import Workshop
from app.repositories.clients import list_client_names
from app.schemas.quotes import QuoteCreate, QuoteCreated, QuoteSent
from app.services import quotes as quote_service

router = APIRouter(prefix="/api/v1/workshop", tags=["workshop"])


@router.get("/clients")
async def list_clients(workshop: Workshop) -> list[str]:
    """F0: los nombres de los clientes del taller de la cabecera X-Workshop-Id."""
    return await list_client_names(workshop.session)


@router.post(
    "/work-orders/{work_order_id}/quotes",
    status_code=status.HTTP_201_CREATED,
)
async def create_quote(
    work_order_id: UUID, body: QuoteCreate, workshop: Workshop
) -> QuoteCreated:
    """F0: crea un presupuesto en borrador con una sola línea."""
    quote_id = await quote_service.create_draft(
        workshop.session,
        workshop.workshop_id,
        work_order_id,
        body.description,
        body.quantity,
        body.unit_price_cents,
        body.vat_bp,
    )
    return QuoteCreated(quote_id=quote_id)


@router.get(
    "/quotes/{quote_id}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def quote_pdf(quote_id: UUID, workshop: Workshop) -> Response:
    pdf = await quote_service.render_quote_pdf(workshop.session, quote_id)
    return pdf_response(pdf, f"presupuesto-{quote_id}.pdf")


@router.post("/quotes/{quote_id}/send")
async def send_quote(quote_id: UUID, workshop: Workshop, request: Request) -> QuoteSent:
    """Congela el presupuesto, guarda su total y genera el enlace de aprobación."""
    sent = await quote_service.send(workshop.session, quote_id)
    url = request.url_for(
        "view_quote", workshop_id=workshop.workshop_id, token=sent.token
    )
    return QuoteSent(
        quote_id=sent.quote_id, total_cents=sent.total_cents, approval_url=str(url)
    )
