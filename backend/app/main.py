from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError
from supertokens_python.framework.fastapi import get_middleware

from app.api.rate_limit import AuthRateLimitMiddleware, retry_after_headers
from app.api.v1.admin.router import router as admin_router
from app.api.v1.invitations.router import router as invitations_router
from app.api.v1.invitations.superadmin import (
    router as superadmin_invitations_router,
)
from app.api.v1.meta import router as meta_router
from app.api.v1.portal.auth import router as portal_auth_router
from app.api.v1.portal.router import router as portal_router
from app.api.v1.workshop.router import router as workshop_router
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import AppError, RateLimitedError
from app.core.supertokens import init_supertokens
from app.infra.email import build_email_sender, set_email_sender
from app.infra.queue import build_job_queue, set_job_queue
from app.infra.rate_limit import build_rate_limiter, set_rate_limiter

# Antes de crear la app: el middleware necesita el SDK ya inicializado.
init_supertokens()

app = FastAPI(title="AXTTON CORE API", version=get_settings().app_version)
# La implementación del correo se elige una vez, al arrancar; los endpoints la
# reciben por dependencia (app/api/deps.py) y las pruebas la sustituyen.
set_email_sender(build_email_sender(get_settings()))
# Y la cola del worker: el enlace del portal se envía desde allí (F5 paso 8).
set_job_queue(build_job_queue(get_settings()))
# Igual el límite de peticiones (RNF-06): las pruebas lo apagan y ponen el suyo.
set_rate_limiter(build_rate_limiter(get_settings()))
# Atiende /api/auth/* (inicio y cierre de sesión, renovación). Sin CORS: con un
# solo dominio, el navegador nunca hace peticiones a otro origen (arquitectura §5).
app.add_middleware(get_middleware())
# En Starlette el ÚLTIMO add_middleware es el más externo: este alcanza
# /api/auth/* antes que SuperTokens, que si no lo atendería sin pasar por aquí.
app.add_middleware(AuthRateLimitMiddleware)

app.include_router(workshop_router)
app.include_router(portal_router)
app.include_router(portal_auth_router)
app.include_router(admin_router)
app.include_router(invitations_router)
app.include_router(superadmin_invitations_router)
app.include_router(meta_router)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """El único sitio donde un error de la aplicación se convierte en HTTP."""
    if isinstance(exc, RateLimitedError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "retry_after": exc.retry_after},
            headers=retry_after_headers(exc.retry_after),
        )
    return JSONResponse(status_code=exc.status_code, content={"code": exc.code})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Un 422 como el de FastAPI, sin lo que mandó quien llama (`input`).

    El manejador por defecto lo devuelve, y un `NaN` o un `Infinity` (que el
    JSON de Python acepta) hacía estallar la respuesta: un 500 en vez del 422
    (lo encontró qa-verifier al cerrar F6). Tampoco hace falta devolver a nadie
    lo que escribió, que puede ser un dato personal."""
    errors = [
        {key: value for key, value in error.items() if key != "input"}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


@app.exception_handler(StaleDataError)
async def stale_data_handler(request: Request, exc: StaleDataError) -> JSONResponse:
    """Bloqueo optimista (RNF-15): otra persona guardó antes. El cambio no se
    aplica y quien guardaba recibe un aviso para decidir, nunca un 500."""
    return JSONResponse(status_code=409, content={"code": "modified_by_someone_else"})


@app.get("/api/health")
async def health(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    """Responde solo si la API llega a la base de datos."""
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}
