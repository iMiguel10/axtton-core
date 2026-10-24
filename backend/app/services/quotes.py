"""Casos de uso de los presupuestos de F0.

El service decide (con ayuda de domain/) y ordena las escrituras; los
repositorios solo hablan con la base de datos. No hace commit: la transacción la
abre y la cierra la dependencia de la petición, así que si algo falla a mitad,
no se guarda nada.
"""

import hashlib
import secrets
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.domain.money import format_eur, format_quantity, format_vat
from app.domain.quotes import (
    WORK_ORDER_AFTER_DECISION,
    WORK_ORDER_AFTER_SEND,
    Line,
    Outcome,
    QuoteStatus,
    line_total_cents,
    quote_total_cents,
)
from app.infra.pdf import render_pdf
from app.repositories import quotes as repo


def hash_token(token: str) -> bytes:
    """Lo que se guarda del enlace secreto: su sha256, nunca el token.

    Un token generado con `secrets` tiene tanta entropía que un hash rápido
    basta; las contraseñas, que son débiles, necesitan algoritmos lentos.
    """
    return hashlib.sha256(token.encode()).digest()


@dataclass(frozen=True)
class SentQuote:
    quote_id: UUID
    total_cents: int
    token: str


async def create_draft(
    session: AsyncSession,
    workshop_id: UUID,
    work_order_id: UUID,
    description: str,
    quantity: Decimal,
    unit_price_cents: int,
    vat_bp: int,
) -> UUID:
    if await repo.lock_work_order(session, work_order_id) is None:
        raise NotFoundError("work_order_not_found")
    quote_id = await repo.insert_draft(session, workshop_id, work_order_id)
    await repo.insert_line(
        session, workshop_id, quote_id, description, quantity, unit_price_cents, vat_bp
    )
    return quote_id


async def send(session: AsyncSession, quote_id: UUID) -> SentQuote:
    quote = await repo.get_quote(session, quote_id)
    if quote is None:
        raise NotFoundError("quote_not_found")
    # Primero la orden, siempre: así dos envíos simultáneos se ponen en fila.
    await repo.lock_work_order(session, quote.work_order_id)
    quote = await repo.get_quote(session, quote_id)  # releído tras el bloqueo
    if quote is None or quote.status != QuoteStatus.DRAFT:
        raise ConflictError("quote_not_draft")

    lines = await repo.list_lines(session, quote_id)
    # Los totales de las líneas se escriben ANTES de marcar el presupuesto como
    # enviado: después, el trigger de la base de datos ya no deja tocarlas.
    for line in lines:
        total = line_total_cents(
            Line(line.quantity, line.unit_price_cents, line.vat_bp)
        )
        await repo.set_line_total(session, line.id, total)
    total_cents = quote_total_cents(
        [Line(line.quantity, line.unit_price_cents, line.vat_bp) for line in lines]
    )

    token = secrets.token_urlsafe(32)
    await repo.mark_sent(session, quote_id, total_cents, hash_token(token))
    await repo.set_work_order_status(
        session, quote.work_order_id, WORK_ORDER_AFTER_SEND
    )
    return SentQuote(quote_id=quote_id, total_cents=total_cents, token=token)


@dataclass(frozen=True)
class QuoteView:
    status: str
    total_cents: int
    lines: list[repo.LineRow]


async def view_by_token(session: AsyncSession, token: str) -> QuoteView:
    quote = await repo.get_quote_by_token_hash(session, hash_token(token))
    # Mismo error para "no existe", "es de otro taller" y "token inventado".
    if quote is None or quote.total_cents is None:
        raise NotFoundError("quote_not_found")
    lines = await repo.list_lines(session, quote.id)
    return QuoteView(status=quote.status, total_cents=quote.total_cents, lines=lines)


# F0: los talleres aún no tienen zona horaria (llega en F1, R10 de la
# especificación). La fecha se muestra en la de España peninsular.
F0_TIMEZONE = ZoneInfo("Europe/Madrid")

STATUS_LABELS = {
    QuoteStatus.SENT: "pendiente de respuesta",
    QuoteStatus.APPROVED: "aprobado",
    QuoteStatus.REJECTED: "rechazado",
}


async def render_quote_pdf(session: AsyncSession, quote_id: UUID) -> bytes:
    """PDF de una versión enviada, generado siempre desde sus datos congelados.

    Un borrador no tiene PDF: sus líneas aún pueden cambiar y no tiene total.
    """
    header = await repo.get_quote_header(session, quote_id)
    if header is None:
        raise NotFoundError("quote_not_found")
    if header.status == QuoteStatus.DRAFT or header.total_cents is None:
        raise ConflictError("quote_is_draft")
    assert header.sent_at is not None  # garantizado por el CHECK de la tabla
    lines = await repo.list_lines(session, quote_id)
    context = {
        "workshop_name": header.workshop_name,
        "client_name": header.client_name,
        "plate": header.plate,
        "status": STATUS_LABELS[QuoteStatus(header.status)],
        "sent_at": header.sent_at.astimezone(F0_TIMEZONE).strftime("%d/%m/%Y"),
        "lines": [
            {
                "description": line.description,
                "quantity": format_quantity(line.quantity),
                "unit_price": format_eur(line.unit_price_cents),
                "vat": format_vat(line.vat_bp),
                # El total de la línea es el GUARDADO al enviar, no uno recalculado.
                "total": format_eur(line.line_total_cents or 0),
            }
            for line in lines
        ],
        "total": format_eur(header.total_cents),
    }
    return await render_pdf("quote.html", context)


async def render_quote_pdf_by_token(session: AsyncSession, token: str) -> bytes:
    quote = await repo.get_quote_by_token_hash(session, hash_token(token))
    if quote is None:
        raise NotFoundError("quote_not_found")
    return await render_quote_pdf(session, quote.id)


async def decide_by_token(
    session: AsyncSession,
    workshop_id: UUID,
    token: str,
    outcome: Outcome,
    ip: str | None,
    user_agent: str | None,
) -> None:
    quote = await repo.get_quote_by_token_hash(session, hash_token(token))
    if quote is None:
        raise NotFoundError("quote_not_found")
    await repo.lock_work_order(session, quote.work_order_id)
    quote = await repo.get_quote(session, quote.id)
    if quote is None or quote.status != QuoteStatus.SENT:
        raise ConflictError("quote_not_pending")
    await repo.record_decision(
        session, workshop_id, quote.id, outcome.value, ip, user_agent
    )
    await repo.set_work_order_status(
        session, quote.work_order_id, WORK_ORDER_AFTER_DECISION[outcome]
    )
