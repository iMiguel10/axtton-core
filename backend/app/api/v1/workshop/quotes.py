"""Presupuestos de una orden (F3): los ve todo el personal; los prepara el
administrador (especificación §3). El mecánico los ve sin importes si el taller
lo ha desactivado."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.v1.workshop.deps import WorkshopContext, require
from app.domain.permissions import Action
from app.schemas.clients import VersionOnly
from app.schemas.quotes import (
    QuoteCreated,
    QuoteDraftSave,
    QuoteLineRead,
    QuoteRead,
    QuoteSaved,
    QuoteTotalsRead,
    VatGroupRead,
)
from app.services import quotes as quote_service
from app.services.quotes import LineInput, QuoteView

router = APIRouter()

Viewer = Annotated[WorkshopContext, Depends(require(Action.VIEW_ORDERS))]
Manager = Annotated[WorkshopContext, Depends(require(Action.MANAGE_QUOTES))]


def _read(view: QuoteView) -> QuoteRead:
    quote, totals, hidden = view.quote, view.totals, view.prices_hidden
    return QuoteRead(
        id=quote.id,
        version_no=quote.version_no,
        status=quote.status,  # type: ignore[arg-type]
        created_at=quote.created_at,
        sent_at=quote.sent_at,
        valid_until=quote.valid_until,
        cancel_reason=quote.cancel_reason,
        global_discount_kind=quote.global_discount_kind,  # type: ignore[arg-type]
        global_discount_value=None if hidden else quote.global_discount_value,
        lines=[
            QuoteLineRead(
                id=line.id,
                position=line.position,
                kind=line.kind,  # type: ignore[arg-type]
                description=line.description,
                reference=line.reference,
                part_condition=line.part_condition,  # type: ignore[arg-type]
                quantity=line.quantity,
                unit_price_cents=None if hidden else line.unit_price_cents,
                discount_bp=line.discount_bp,
                vat_bp=line.vat_bp,
                taxable_cents=totals.lines[i].taxable_cents if totals else None,
                total_cents=totals.lines[i].total_cents if totals else None,
            )
            for i, line in enumerate(view.lines)
        ],
        totals=(
            QuoteTotalsRead(
                subtotal_cents=totals.subtotal_cents,
                global_discount_cents=totals.global_discount_cents,
                vat_breakdown=[
                    VatGroupRead(
                        vat_bp=g.vat_bp, base_cents=g.base_cents, vat_cents=g.vat_cents
                    )
                    for g in totals.vat_breakdown
                ],
                total_cents=totals.total_cents,
            )
            if totals
            else None
        ),
        prices_hidden=hidden,
        version=quote.version,
    )


@router.get("/orders/{order_id}/quotes")
async def list_quotes(order_id: UUID, workshop: Viewer) -> list[QuoteRead]:
    views = await quote_service.list_quotes(
        workshop.session, workshop.workshop_id, order_id, workshop.role
    )
    return [_read(view) for view in views]


@router.post("/orders/{order_id}/quotes", status_code=status.HTTP_201_CREATED)
async def create_draft(order_id: UUID, workshop: Manager) -> QuoteCreated:
    """Una versión nueva en borrador; si ya hay versiones, copia la última."""
    quote_id = await quote_service.create_draft(
        workshop.session, workshop.workshop_id, workshop.employee_id, order_id
    )
    return QuoteCreated(id=quote_id)


@router.put("/quotes/{quote_id}")
async def save_draft(
    quote_id: UUID, body: QuoteDraftSave, workshop: Manager
) -> QuoteSaved:
    version = await quote_service.save_draft(
        workshop.session,
        workshop.workshop_id,
        quote_id,
        expected_version=body.version,
        global_discount=(
            body.global_discount.model_dump(mode="json")
            if body.global_discount
            else None
        ),
        lines=[LineInput(**line.model_dump()) for line in body.lines],
    )
    return QuoteSaved(version=version)


@router.post("/quotes/{quote_id}/discard", status_code=status.HTTP_204_NO_CONTENT)
async def discard_draft(quote_id: UUID, body: VersionOnly, workshop: Manager) -> None:
    await quote_service.discard_draft(
        workshop.session, quote_id, expected_version=body.version
    )
