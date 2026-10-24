from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.portal.router import router as portal_router
from app.api.v1.workshop.router import router as workshop_router
from app.core.db import get_session
from app.core.errors import AppError

app = FastAPI(title="AXTTON CORE API", version="0.1.0")
app.include_router(workshop_router)
app.include_router(portal_router)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """El único sitio donde un error de la aplicación se convierte en HTTP."""
    return JSONResponse(status_code=exc.status_code, content={"code": exc.code})


@app.get("/api/health")
async def health(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    """Responde solo si la API llega a la base de datos."""
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}
