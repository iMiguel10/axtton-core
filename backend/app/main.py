from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session

app = FastAPI(title="AXTTON CORE API", version="0.1.0")


@app.get("/api/health")
async def health(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    """Responde solo si la API llega a la base de datos."""
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}
