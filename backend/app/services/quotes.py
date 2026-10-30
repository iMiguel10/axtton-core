"""Presupuestos de una orden: el borrador (F3 paso 4, RF-30 a RF-32, RF-38).

Un borrador se edita libremente (RF-31): guardar es reemplazar sus líneas y su
descuento global de una vez, con su `version` como bloqueo optimista (RNF-15).
Corregir una versión enviada es crear la siguiente, copiando la anterior
(RF-32). Enviar, anular y decidir llegan en los pasos 5 y 6.

Bloqueos, siempre en este orden: la orden con FOR SHARE (un borrador no cambia
la orden, pero un envío, que pide FOR UPDATE, no debe cruzarse con él) y
después la versión con FOR UPDATE.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.domain.permissions import Role
from app.domain.quotes import (
    MAX_VERSIONS_PER_ORDER,
    DiscountKind,
    GlobalDiscount,
    Line,
    LineKind,
    LineTotals,
    QuoteRuleError,
    QuoteStatus,
    QuoteTotals,
    VatGroup,
    compute,
)
from app.domain.work_orders import CLOSED
from app.models import Quote, QuoteLine, WorkOrder, Workshop
from app.repositories import quotes as quote_repo
from app.repositories import work_orders as order_repo
from app.services.integrity import flush_or_conflict

# Dos borradores a la vez para la misma orden: el segundo choca con uno de los
# dos índices (un solo borrador, número de versión único).
UNIQUE = {
    "uq_quotes_work_order_id_draft": "quote_draft_exists",
    "uq_quotes_work_order_id_version_no": "quote_draft_exists",
}

# Lo que se copia de una línea al crear la versión siguiente: lo que escribió
# quien la preparó, nunca sus importes, que se calculan al enviar.
COPIED = (
    "position",
    "kind",
    "description",
    "reference",
    "part_condition",
    "quantity",
    "unit_price_cents",
    "discount_bp",
    "vat_bp",
    "optional",
)


@dataclass(frozen=True)
class LineInput:
    kind: LineKind
    description: str
    reference: str | None
    part_condition: str | None
    quantity: Decimal
    unit_price_cents: int
    discount_bp: int
    vat_bp: int


@dataclass(frozen=True)
class QuoteView:
    quote: Quote
    lines: list[QuoteLine]
    # Los guardados al enviar o, en un borrador, el cálculo de cómo quedaría.
    totals: QuoteTotals | None
    # El mecánico no ve importes si el taller lo desactiva (especificación §3).
    prices_hidden: bool


def _as_domain(line: QuoteLine | LineInput) -> Line:
    return Line(line.quantity, line.unit_price_cents, line.vat_bp, line.discount_bp)


def _global(kind: str | None, value: int | None) -> GlobalDiscount | None:
    if kind is None or value is None:
        return None
    return GlobalDiscount(DiscountKind(kind), value)


def _calculate(
    lines: list[QuoteLine] | list[LineInput], discount: GlobalDiscount | None
) -> QuoteTotals:
    """La regla única (domain/quotes.py). Lo que no se puede calcular es un 422
    con su código (invalid_quantity, global_discount_exceeds_subtotal…)."""
    try:
        return compute([_as_domain(line) for line in lines], discount)
    except QuoteRuleError as error:
        raise ValidationFailedError(error.code) from error


def _stored_totals(quote: Quote, lines: list[QuoteLine]) -> QuoteTotals:
    """Los totales de una versión enviada, tal como se guardaron: no se vuelven
    a calcular nunca (RNF-11, RNF-14)."""
    assert quote.total_cents is not None and quote.vat_breakdown is not None
    return QuoteTotals(
        lines=tuple(
            LineTotals(
                gross_cents=line.gross_cents or 0,
                discount_cents=line.discount_cents or 0,
                global_discount_share_cents=line.global_discount_share_cents or 0,
                taxable_cents=line.taxable_cents or 0,
                vat_cents=line.vat_cents or 0,
                total_cents=line.line_total_cents or 0,
            )
            for line in lines
        ),
        subtotal_cents=quote.subtotal_cents or 0,
        global_discount_cents=quote.global_discount_cents or 0,
        vat_breakdown=tuple(
            VatGroup(g["vat_bp"], g["base_cents"], g["vat_cents"])
            for g in quote.vat_breakdown
        ),
        total_cents=quote.total_cents,
    )


async def _prices_hidden(session: AsyncSession, workshop_id: UUID, role: str) -> bool:
    if role != Role.MECHANIC:
        return False
    workshop = await session.get(Workshop, workshop_id)
    assert workshop is not None
    return not workshop.mechanics_see_sale_prices


async def list_quotes(
    session: AsyncSession, workshop_id: UUID, order_id: UUID, role: str
) -> list[QuoteView]:
    if await order_repo.get(session, order_id) is None:
        raise NotFoundError("work_order_not_found")
    quotes = await quote_repo.list_for_order(session, order_id)
    lines = await quote_repo.lines_of(session, [q.id for q in quotes])
    hidden = await _prices_hidden(session, workshop_id, role)
    views = []
    for quote in quotes:
        own = lines.get(quote.id, [])
        if quote.status == QuoteStatus.DRAFT:
            totals = _calculate(
                own, _global(quote.global_discount_kind, quote.global_discount_value)
            )
        else:
            totals = _stored_totals(quote, own)
        views.append(QuoteView(quote, own, None if hidden else totals, hidden))
    return views


async def _locked_open_order(session: AsyncSession, order_id: UUID) -> WorkOrder:
    order = await order_repo.get_for_share(session, order_id)
    if order is None:
        raise NotFoundError("work_order_not_found")
    # Una orden cerrada solo admite notas y su cobro (RF-26).
    if order.status in CLOSED:
        raise ConflictError("work_order_closed")
    return order


async def create_draft(
    session: AsyncSession, workshop_id: UUID, employee_id: UUID, order_id: UUID
) -> UUID:
    """Una versión nueva en borrador. Si ya hay versiones, copia las líneas y el
    descuento de la última (RF-32): corregir es partir de lo que se envió."""
    await _locked_open_order(session, order_id)
    if await quote_repo.has_draft(session, order_id):
        raise ConflictError("quote_draft_exists")
    if await quote_repo.versions_count(session, order_id) >= MAX_VERSIONS_PER_ORDER:
        raise ConflictError("quote_version_limit_reached")
    previous = await quote_repo.latest(session, order_id)
    draft = Quote(
        workshop_id=workshop_id,
        work_order_id=order_id,
        version_no=(previous.version_no + 1) if previous else 1,
        created_by_employee_id=employee_id,
        global_discount_kind=previous.global_discount_kind if previous else None,
        global_discount_value=previous.global_discount_value if previous else None,
    )
    session.add(draft)
    await flush_or_conflict(session, UNIQUE)
    if previous is not None:
        old = (await quote_repo.lines_of(session, [previous.id])).get(previous.id, [])
        for line in old:
            session.add(
                QuoteLine(
                    workshop_id=workshop_id,
                    quote_id=draft.id,
                    **{field: getattr(line, field) for field in COPIED},
                )
            )
        await session.flush()
    return draft.id


async def _locked_draft(
    session: AsyncSession, quote_id: UUID, expected_version: int
) -> Quote:
    found = await quote_repo.get(session, quote_id)
    if found is None:
        raise NotFoundError("quote_not_found")
    await _locked_open_order(session, found.work_order_id)
    quote = await quote_repo.get_for_update(session, quote_id)
    assert quote is not None
    if quote.status != QuoteStatus.DRAFT:
        raise ConflictError("quote_not_draft")
    if quote.version != expected_version:
        raise ConflictError("modified_by_someone_else")
    return quote


async def save_draft(
    session: AsyncSession,
    workshop_id: UUID,
    quote_id: UUID,
    *,
    expected_version: int,
    global_discount: dict[str, Any] | None,
    lines: list[LineInput],
) -> int:
    """Reemplaza las líneas y el descuento del borrador. Antes de guardar se
    calcula con la regla única: lo que luego no se podría enviar (un descuento
    mayor que el presupuesto) se rechaza ya ahora. Devuelve la versión nueva."""
    quote = await _locked_draft(session, quote_id, expected_version)
    discount = (
        GlobalDiscount(DiscountKind(global_discount["kind"]), global_discount["value"])
        if global_discount
        else None
    )
    _calculate(lines, discount)
    await quote_repo.delete_lines(session, quote.id)
    await session.flush()
    for position, line in enumerate(lines, start=1):
        session.add(
            QuoteLine(
                workshop_id=workshop_id,
                quote_id=quote.id,
                position=position,
                kind=line.kind,
                description=line.description,
                reference=line.reference,
                part_condition=line.part_condition,
                quantity=line.quantity,
                unit_price_cents=line.unit_price_cents,
                discount_bp=line.discount_bp,
                vat_bp=line.vat_bp,
            )
        )
    quote.global_discount_kind = discount.kind if discount else None
    quote.global_discount_value = discount.value if discount else None
    # Aunque solo cambien las líneas, la versión sube: es lo que avisa a quien
    # edita el mismo borrador a la vez (RNF-15).
    quote.updated_at = datetime.now(UTC)
    await session.flush()
    return quote.version


async def discard_draft(
    session: AsyncSession, quote_id: UUID, *, expected_version: int
) -> None:
    """Descartar un borrador es borrarlo, con sus líneas (especificación §6)."""
    quote = await _locked_draft(session, quote_id, expected_version)
    await quote_repo.delete_lines(session, quote.id)
    await session.delete(quote)
    await session.flush()
