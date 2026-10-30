"""Presupuestos de una orden: el borrador (F3 paso 4, RF-30 a RF-32, RF-38), el
envío y la anulación (paso 5, arquitectura §7.1). Decidir llega en el paso 6.

Un borrador se edita libremente (RF-31): guardar es reemplazar sus líneas y su
descuento global de una vez, con su `version` como bloqueo optimista (RNF-15).
Corregir una versión enviada es crear la siguiente, copiando la anterior
(RF-32).

Bloqueos, siempre en este orden: primero la orden y después la versión con FOR
UPDATE. La orden, con FOR SHARE para editar un borrador (no la cambia) y con
FOR UPDATE para enviar o anular (le cambian el estado): así un envío y un
guardado del mismo borrador nunca se cruzan.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.domain.business_days import quote_valid_until
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
from app.domain.work_orders import CLOSED, StatusChangeCause, WorkOrderStatus
from app.models import AuditEntry, Quote, QuoteLine, WorkOrder, Workshop
from app.repositories import quotes as quote_repo
from app.repositories import vehicles as vehicle_repo
from app.repositories import work_orders as order_repo
from app.services.integrity import flush_or_conflict
from app.services.work_orders import record_status_change

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
    expired: bool


def is_expired(quote: Quote, now: datetime) -> bool:
    """Caducada (RF-33): marcada como tal, o enviada y pasado su plazo aunque
    nadie la haya marcado todavía (hasta el worker, F5, nadie escribe
    `expired`). Ya no se puede aprobar: el trigger de las decisiones lo mira
    con la hora del servidor."""
    if quote.status == QuoteStatus.EXPIRED:
        return True
    return (
        quote.status == QuoteStatus.SENT
        and quote.valid_until is not None
        and quote.valid_until <= now
    )


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
        views.append(
            QuoteView(
                quote,
                own,
                None if hidden else totals,
                hidden,
                is_expired(quote, datetime.now(UTC)),
            )
        )
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
    previous = await quote_repo.latest(session, order_id)
    draft = await _new_version(session, workshop_id, employee_id, order_id, previous)
    return draft.id


async def _new_version(
    session: AsyncSession,
    workshop_id: UUID,
    employee_id: UUID,
    order_id: UUID,
    source: Quote | None,
) -> Quote:
    """La versión siguiente, en borrador, copiando las líneas y el descuento de
    `source` (si hay). Va con la orden ya bloqueada por quien la llama."""
    if await quote_repo.has_draft(session, order_id):
        raise ConflictError("quote_draft_exists")
    if await quote_repo.versions_count(session, order_id) >= MAX_VERSIONS_PER_ORDER:
        raise ConflictError("quote_version_limit_reached")
    latest = await quote_repo.latest(session, order_id)
    draft = Quote(
        workshop_id=workshop_id,
        work_order_id=order_id,
        version_no=(latest.version_no + 1) if latest else 1,
        created_by_employee_id=employee_id,
        global_discount_kind=source.global_discount_kind if source else None,
        global_discount_value=source.global_discount_value if source else None,
    )
    session.add(draft)
    await flush_or_conflict(session, UNIQUE)
    if source is not None:
        old = (await quote_repo.lines_of(session, [source.id])).get(source.id, [])
        for line in old:
            session.add(
                QuoteLine(
                    workshop_id=workshop_id,
                    quote_id=draft.id,
                    **{field: getattr(line, field) for field in COPIED},
                )
            )
        await session.flush()
    return draft


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


# --- El listado (la entrada "Presupuestos" de la barra lateral) ----------------


@dataclass(frozen=True)
class ListedQuote:
    row: quote_repo.QuoteRow
    # El total guardado, o el calculado si es un borrador; nulo si quien mira
    # no puede ver importes.
    total_cents: int | None
    # Enviada y pasado su plazo, aunque nadie la haya marcado (hasta F5).
    expired: bool


async def list_page(
    session: AsyncSession,
    workshop_id: UUID,
    role: str,
    *,
    view: quote_repo.ListView,
    limit: int,
    offset: int,
) -> list[ListedQuote]:
    rows = await quote_repo.list_page(session, view=view, limit=limit, offset=offset)
    hidden = await _prices_hidden(session, workshop_id, role)
    drafts = [r.quote.id for r in rows if r.quote.status == QuoteStatus.DRAFT]
    draft_lines = await quote_repo.lines_of(session, drafts) if not hidden else {}
    now = datetime.now(UTC)
    listed = []
    for row in rows:
        quote = row.quote
        total: int | None
        if hidden:
            total = None
        elif quote.status == QuoteStatus.DRAFT:
            discount = _global(quote.global_discount_kind, quote.global_discount_value)
            total = _calculate(draft_lines.get(quote.id, []), discount).total_cents
        else:
            total = quote.total_cents
        listed.append(ListedQuote(row, total, is_expired(quote, now)))
    return listed


# --- Enviar y anular (F3 paso 5, arquitectura §7.1, especificación §6) ---------

# Desde dónde se envía: el presupuesto inicial, tras diagnosticar; un trabajo
# adicional, durante la reparación; y una corrección, con otra versión ya
# esperando respuesta (la sustituye y hereda su estado de origen).
SEND_FROM = frozenset(
    {
        WorkOrderStatus.DIAGNOSING,
        WorkOrderStatus.IN_REPAIR,
        WorkOrderStatus.PENDING_APPROVAL,
    }
)


async def _locked_for_status_change(
    session: AsyncSession, quote_id: UUID, expected_version: int
) -> tuple[WorkOrder, Quote]:
    """La orden con FOR UPDATE (enviar o anular le cambian el estado) y después
    la versión con FOR UPDATE, siempre en ese orden. Un borrador que se esté
    guardando a la vez tiene la orden con FOR SHARE: el envío espera, luego ve
    la versión nueva del borrador y la de quien envía ya no coincide (409)."""
    found = await quote_repo.get(session, quote_id)
    if found is None:
        raise NotFoundError("quote_not_found")
    order = await order_repo.get_for_update(session, found.work_order_id)
    assert order is not None  # FK: la versión no existe sin su orden
    if order.status in CLOSED:
        raise ConflictError("work_order_closed")
    quote = await quote_repo.get_for_update(session, quote_id)
    assert quote is not None
    if quote.version != expected_version:
        raise ConflictError("modified_by_someone_else")
    return order, quote


async def send_quote(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    employee_id: UUID,
    quote_id: UUID,
    *,
    expected_version: int,
) -> None:
    """Envía un borrador: lo congela con sus totales y mueve la orden a
    `pending_approval` (arquitectura §7.1). El aviso al cliente llega con el
    worker (F5).

    El orden de las escrituras lo imponen los triggers de 0013quotes:
    1. la versión enviada anterior pasa a sustituida antes de que haya otra (el
       índice único de `sent` no es diferible);
    2. los importes de las líneas, mientras la versión aún es un borrador, en
       su propio `flush`: en uno solo, el ORM escribiría antes la versión;
    3. la versión, con sus totales (el trigger comprueba que las líneas suman);
    4. el estado de la orden, con su cambio en el historial (invariante 5).
    """
    order, quote = await _locked_for_status_change(session, quote_id, expected_version)
    if quote.status != QuoteStatus.DRAFT:
        raise ConflictError("quote_not_draft")
    if order.status not in SEND_FROM:
        raise ConflictError("quote_cannot_be_sent_now")
    replaced = await quote_repo.awaiting_version(session, order.id)
    await _freeze_and_send(
        session,
        workshop_id,
        user_id,
        employee_id,
        order,
        quote,
        replaced=replaced,
        action="quote_sent",
    )


async def renew_quote(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    employee_id: UUID,
    quote_id: UUID,
    *,
    expected_version: int,
) -> UUID:
    """Renueva una versión enviada, caducada o no: crea la siguiente con las
    mismas líneas, precios y descuento y la envía en el acto, con una validez
    nueva desde hoy. La renovada pasa a sustituida y conserva su estado de
    origen. Es "ampliar el plazo" sin tocar lo que se envió (invariante 6):
    su PDF sigue saliendo idéntico. Devuelve la versión nueva."""
    order, quote = await _locked_for_status_change(session, quote_id, expected_version)
    if quote.status not in (QuoteStatus.SENT, QuoteStatus.EXPIRED):
        raise ConflictError("quote_not_renewable")
    renewed = await _new_version(session, workshop_id, employee_id, order.id, quote)
    await _freeze_and_send(
        session,
        workshop_id,
        user_id,
        employee_id,
        order,
        renewed,
        replaced=quote,
        action="quote_renewed",
    )
    return renewed.id


async def _freeze_and_send(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    employee_id: UUID,
    order: WorkOrder,
    quote: Quote,
    *,
    replaced: Quote | None,
    action: str,
) -> None:
    """Congela un borrador con sus totales y lo envía. `replaced` es la versión
    que esperaba respuesta (si hay): pasa a sustituida y le deja su estado de
    origen. Va con la orden y la versión ya bloqueadas, en ese orden."""
    lines = (await quote_repo.lines_of(session, [quote.id])).get(quote.id, [])
    if not lines:
        raise ConflictError("quote_empty")
    totals = _calculate(
        lines, _global(quote.global_discount_kind, quote.global_discount_value)
    )

    if replaced is not None:
        replaced.status = QuoteStatus.SUPERSEDED
        await session.flush()
    for line, amounts in zip(lines, totals.lines, strict=True):
        line.gross_cents = amounts.gross_cents
        line.discount_cents = amounts.discount_cents
        line.global_discount_share_cents = amounts.global_discount_share_cents
        line.taxable_cents = amounts.taxable_cents
        line.vat_cents = amounts.vat_cents
        line.line_total_cents = amounts.total_cents
    await session.flush()

    # Todo lo que se lee, antes de tocar la versión: una consulta a mitad
    # provocaría un autoflush de la versión "enviada" sin sus totales, y el CHECK
    # ck_quotes_sent_fields la rechazaría.
    workshop = await session.get(Workshop, workshop_id)
    assert workshop is not None
    sent_at = await vehicle_repo.db_now(session)
    diagnosis_id = await quote_repo.latest_diagnosis_id(session, order.id)
    quote.status = QuoteStatus.SENT
    quote.sent_at = sent_at
    quote.sent_by_employee_id = employee_id
    quote.valid_until = quote_valid_until(
        sent_at, workshop.timezone, workshop.quote_validity_business_days
    )
    # Si sustituye a una versión que esperaba respuesta, vuelve adonde volvía
    # ella: la orden ya está en `pending_approval` por la anterior.
    quote.origin_status = (
        replaced.origin_status
        if replaced is not None and replaced.origin_status
        else order.status
    )
    quote.diagnosis_version_id = diagnosis_id
    quote.subtotal_cents = totals.subtotal_cents
    quote.global_discount_cents = totals.global_discount_cents
    quote.vat_breakdown = [
        {"vat_bp": g.vat_bp, "base_cents": g.base_cents, "vat_cents": g.vat_cents}
        for g in totals.vat_breakdown
    ]
    quote.total_cents = totals.total_cents
    await session.flush()

    if order.status != WorkOrderStatus.PENDING_APPROVAL:
        await record_status_change(
            session,
            order,
            WorkOrderStatus.PENDING_APPROVAL,
            cause=StatusChangeCause.QUOTE_SENT,
            employee_id=employee_id,
        )
    session.add(
        AuditEntry(
            workshop_id=workshop_id,
            actor_user_id=user_id,
            action=action,
            target_type="work_order",
            target_id=order.id,
            details={
                "quote_version": quote.version_no,
                "total_cents": totals.total_cents,
            },
        )
    )
    await session.flush()


async def cancel_quote(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    employee_id: UUID,
    quote_id: UUID,
    *,
    expected_version: int,
    reason: str,
) -> None:
    """Anula una versión enviada, con motivo (§6): el taller la retira. Si era
    la que esperaba respuesta, la orden vuelve al estado desde el que se envió.
    El aviso al cliente, si ya la había recibido, llega con el worker (F5)."""
    order, quote = await _locked_for_status_change(session, quote_id, expected_version)
    # Enviada (también pasado su plazo) o ya marcada como caducada.
    if quote.status not in (QuoteStatus.SENT, QuoteStatus.EXPIRED):
        raise ConflictError("quote_not_cancellable")
    was_waiting = quote.status == QuoteStatus.SENT
    quote.status = QuoteStatus.CANCELLED
    quote.cancel_reason = reason
    await session.flush()
    if (
        was_waiting
        and order.status == WorkOrderStatus.PENDING_APPROVAL
        and quote.origin_status is not None
    ):
        await record_status_change(
            session,
            order,
            quote.origin_status,
            cause=StatusChangeCause.QUOTE_CANCELLED,
            employee_id=employee_id,
            note=reason,
        )
    session.add(
        AuditEntry(
            workshop_id=workshop_id,
            actor_user_id=user_id,
            action="quote_cancelled",
            target_type="work_order",
            target_id=order.id,
            details={"quote_version": quote.version_no, "cancel_reason": reason},
        )
    )
    await session.flush()
