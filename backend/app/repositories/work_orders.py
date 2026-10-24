from collections.abc import Sequence

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_work_order_rows(session: AsyncSession) -> Sequence[Row]:  # type: ignore[type-arg]
    """Órdenes del taller fijado, con su cliente, su matrícula y su último presupuesto."""
    result = await session.execute(
        text(
            """
            SELECT o.id, o.status, c.name AS client_name, v.plate,
                   q.id AS quote_id, q.status AS quote_status
            FROM work_orders o
            JOIN clients c ON c.id = o.client_id
            JOIN vehicles v ON v.id = o.vehicle_id
            LEFT JOIN LATERAL (
                SELECT id, status FROM quotes
                WHERE work_order_id = o.id
                ORDER BY created_at DESC LIMIT 1
            ) q ON true
            ORDER BY o.created_at
            """
        )
    )
    return result.all()
