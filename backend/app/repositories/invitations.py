from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Invitation


async def get_by_token_hash(
    session: AsyncSession, token_hash: bytes, *, lock: bool = False
) -> Invitation | None:
    """Invitación del taller fijado (RLS) con ese hash.

    Con lock=True la fila queda bloqueada hasta el final de la transacción: dos
    aceptaciones simultáneas del mismo enlace se ponen en fila, y la segunda ve
    que la primera ya la aceptó.
    """
    query = select(Invitation).where(Invitation.token_hash == token_hash)
    if lock:
        query = query.with_for_update()
    return (await session.scalars(query)).one_or_none()
