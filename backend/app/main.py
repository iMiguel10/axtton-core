from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from supertokens_python.framework.fastapi import get_middleware

from app.api.v1.admin.router import router as admin_router
from app.api.v1.portal.router import router as portal_router
from app.api.v1.workshop.router import router as workshop_router
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import AppError
from app.core.supertokens import init_supertokens
from app.infra.email import build_email_sender

# Antes de crear la app: el middleware necesita el SDK ya inicializado.
init_supertokens()

app = FastAPI(title="AXTTON CORE API", version="0.1.0")
# La implementación del correo se elige una vez, al arrancar; los endpoints la
# reciben por dependencia (app/api/deps.py) y las pruebas la sustituyen.
app.state.email_sender = build_email_sender(get_settings())
# Atiende /api/auth/* (inicio y cierre de sesión, renovación). Sin CORS: con un
# solo dominio, el navegador nunca hace peticiones a otro origen (arquitectura §5).
app.add_middleware(get_middleware())

app.include_router(workshop_router)
app.include_router(portal_router)
app.include_router(admin_router)


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
