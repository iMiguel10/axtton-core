from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def get_by_supertokens_id(
    session: AsyncSession, supertokens_user_id: str
) -> User | None:
    """La cuenta propia ligada a un usuario de SuperTokens.

    `users` no tiene taller ni RLS: se consulta antes de saber en qué taller se
    trabaja (al iniciar sesión).
    """
    result = await session.scalars(
        select(User).where(User.supertokens_user_id == supertokens_user_id)
    )
    return result.one_or_none()
