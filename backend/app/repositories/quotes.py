"""Consultas de presupuestos. Siempre bajo RLS (sesión de axtton_app con el taller fijado).

F0 usa SQL escrito a mano para que se vea qué llega a Postgres; los modelos de
SQLAlchemy llegan con F1.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class QuoteRow:
    id: UUID
    work_order_id: UUID
    status: str
    total_cents: int | None


@dataclass(frozen=True)
class LineRow:
    id: UUID
    description: str
    quantity: Decimal
    unit_price_cents: int
    vat_bp: int
    line_total_cents: int | None


async def lock_work_order(session: AsyncSession, work_order_id: UUID) -> str | None:
    """Bloquea la orden hasta el final de la transacción y devuelve su estado.

    Dos peticiones que cambian la misma orden a la vez (dos envíos, dos
    decisiones) quedan en fila: la segunda espera aquí y después ve lo que hizo
    la primera.
    """
    return await session.scalar(
        text("SELECT status FROM work_orders WHERE id = :id FOR UPDATE"),
        {"id": work_order_id},
    )


async def set_work_order_status(
    session: AsyncSession, work_order_id: UUID, status: str
) -> None:
    await session.execute(
        text("UPDATE work_orders SET status = :s WHERE id = :id"),
        {"s": status, "id": work_order_id},
    )


async def insert_draft(
    session: AsyncSession, workshop_id: UUID, work_order_id: UUID
) -> UUID:
    quote_id: UUID = await session.scalar(
        text(
            "INSERT INTO quotes (workshop_id, work_order_id) VALUES (:w, :o) RETURNING id"
        ),
        {"w": workshop_id, "o": work_order_id},
    )
    return quote_id


async def insert_line(
    session: AsyncSession,
    workshop_id: UUID,
    quote_id: UUID,
    description: str,
    quantity: Decimal,
    unit_price_cents: int,
    vat_bp: int,
) -> None:
    await session.execute(
        text(
            "INSERT INTO quote_lines"
            " (workshop_id, quote_id, description, quantity, unit_price_cents, vat_bp)"
            " VALUES (:w, :q, :d, :qty, :p, :v)"
        ),
        {
            "w": workshop_id,
            "q": quote_id,
            "d": description,
            "qty": quantity,
            "p": unit_price_cents,
            "v": vat_bp,
        },
    )


async def get_quote(session: AsyncSession, quote_id: UUID) -> QuoteRow | None:
    row = (
        await session.execute(
            text(
                "SELECT id, work_order_id, status, total_cents FROM quotes WHERE id = :id"
            ),
            {"id": quote_id},
        )
    ).one_or_none()
    return QuoteRow(*row) if row else None


async def get_quote_by_token_hash(
    session: AsyncSession, token_hash: bytes
) -> QuoteRow | None:
    row = (
        await session.execute(
            text(
                "SELECT id, work_order_id, status, total_cents FROM quotes"
                " WHERE approval_token_hash = :h"
            ),
            {"h": token_hash},
        )
    ).one_or_none()
    return QuoteRow(*row) if row else None


@dataclass(frozen=True)
class QuoteHeaderRow:
    status: str
    total_cents: int | None
    sent_at: datetime | None
    workshop_name: str
    client_name: str
    plate: str


async def get_quote_header(
    session: AsyncSession, quote_id: UUID
) -> QuoteHeaderRow | None:
    """Lo que necesita la cabecera del PDF. Los JOIN también pasan por RLS:
    cada tabla filtra por el taller fijado."""
    row = (
        await session.execute(
            text(
                """
                SELECT q.status, q.total_cents, q.sent_at,
                       w.name, c.name, v.plate
                FROM quotes q
                JOIN work_orders o ON o.id = q.work_order_id
                JOIN workshops w ON w.id = q.workshop_id
                JOIN clients c ON c.id = o.client_id
                JOIN vehicles v ON v.id = o.vehicle_id
                WHERE q.id = :id
                """
            ),
            {"id": quote_id},
        )
    ).one_or_none()
    return QuoteHeaderRow(*row) if row else None


async def list_lines(session: AsyncSession, quote_id: UUID) -> list[LineRow]:
    rows = await session.execute(
        text(
            "SELECT id, description, quantity, unit_price_cents, vat_bp, line_total_cents"
            " FROM quote_lines WHERE quote_id = :q ORDER BY created_at, id"
        ),
        {"q": quote_id},
    )
    return [LineRow(*row) for row in rows]


async def set_line_total(session: AsyncSession, line_id: UUID, total: int) -> None:
    await session.execute(
        text("UPDATE quote_lines SET line_total_cents = :t WHERE id = :id"),
        {"t": total, "id": line_id},
    )


async def mark_sent(
    session: AsyncSession, quote_id: UUID, total_cents: int, token_hash: bytes
) -> None:
    await session.execute(
        text(
            "UPDATE quotes SET status = 'sent', total_cents = :t,"
            " sent_at = clock_timestamp(), approval_token_hash = :h WHERE id = :id"
        ),
        {"t": total_cents, "h": token_hash, "id": quote_id},
    )


async def record_decision(
    session: AsyncSession,
    workshop_id: UUID,
    quote_id: UUID,
    outcome: str,
    ip: str | None,
    user_agent: str | None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO quote_decisions"
            " (workshop_id, quote_id, outcome, channel, ip, user_agent)"
            " VALUES (:w, :q, :o, 'portal', CAST(:ip AS inet), :ua)"
        ),
        {
            "w": workshop_id,
            "q": quote_id,
            "o": outcome,
            "ip": ip,
            "ua": user_agent,
        },
    )
    await session.execute(
        text("UPDATE quotes SET status = :o WHERE id = :id"),
        {"o": outcome, "id": quote_id},
    )
