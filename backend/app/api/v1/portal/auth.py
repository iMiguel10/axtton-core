"""Entrar en el portal: la página de cada taller, pedir el enlace y consumirlo
(arquitectura §7.2, decisión 0006).

Son las únicas rutas de /api/v1/portal sin sesión: quien las usa todavía no la
tiene. Por eso no cuelgan del router del portal, que exige el actor cliente, y
la prueba T1 las nombra como excepción (`PUBLIC_ROUTES` en test_auth.py).

Casi todas llevan el taller, así que van por la política normal: fijan ese taller
y buscan bajo RLS. La única que cruza talleres es buscar uno por su nombre corto,
por la vía de plataforma con nombre (decisión 0007, R8_EXCEPTIONS).
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status

from app.api.deps import get_email_sender
from app.api.rate_limit import (
    limit_portal_consume,
    limit_portal_entry,
    limit_portal_link,
)
from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.core.sessions import create_client_session
from app.domain.clients import normalize_email
from app.domain.portal import normalize_slug, slug_problem
from app.infra.email import EmailSender, compose
from app.platform.portal_entry import workshop_id_by_slug
from app.schemas.portal import (
    PortalEntryRead,
    PortalLinkConsume,
    PortalLinkRequest,
    PortalSlugRead,
)
from app.services import portal_auth as portal_auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/portal", tags=["portal"])


@router.get("/workshops/by-slug/{slug}")
async def workshop_by_slug(slug: str, request: Request) -> PortalSlugRead:
    """El taller de `/portal/{nombre}` (decisión 0007). 404 si no hay ningún taller
    activo con ese nombre; uno que no es un nombre válido, ni se busca."""
    await limit_portal_entry(request)
    normalized = normalize_slug(slug)
    found = None if slug_problem(normalized) else await workshop_id_by_slug(normalized)
    if found is None:
        raise NotFoundError("workshop_not_found")
    return PortalSlugRead(workshop_id=found)


@router.get("/workshops/{workshop_id}")
async def workshop_entry(workshop_id: UUID, request: Request) -> PortalEntryRead:
    """El taller de una página de entrada (`/portal/login/{taller}`). 404 si no
    existe o está desactivado."""
    await limit_portal_entry(request)
    entry = await portal_auth_service.entry(workshop_id)
    return PortalEntryRead(workshop_name=entry.workshop_name, has_logo=entry.has_logo)


@router.get("/workshops/{workshop_id}/logo")
async def workshop_logo(workshop_id: UUID, request: Request) -> Response:
    """El logotipo de la entrada, el PNG que volvió a dibujar el servidor."""
    await limit_portal_entry(request)
    logo = await portal_auth_service.entry_logo(workshop_id)
    return Response(
        content=logo.content,
        media_type=logo.media_type,
        headers={
            # Es público, como el nombre del taller; si lo cambia, se ve en minutos.
            "Cache-Control": "public, max-age=300",
            "X-Content-Type-Options": "nosniff",
            # Abierto suelto en el navegador, que no ejecute nada.
            "Content-Security-Policy": "default-src 'none'",
        },
    )


async def _send_link(workshop_id: UUID, email: str, email_sender: EmailSender) -> None:
    """Emite y envía, después de responder.

    En segundo plano para que la respuesta no dependa de si el email es de un
    cliente: ni en lo que dice ni en lo que tarda (RF-41). Un fallo aquí no llega
    a quien lo pidió; queda en el registro.
    """
    try:
        content = await portal_auth_service.issue_link(
            workshop_id, email, app_url=get_settings().app_url
        )
        if content is not None:
            await email_sender.send(compose(email, content))
    except Exception:
        logger.exception("No se pudo enviar el acceso al portal")


@router.post("/auth/request-link", status_code=status.HTTP_202_ACCEPTED)
async def request_link(
    body: PortalLinkRequest,
    request: Request,
    background: BackgroundTasks,
    email_sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> None:
    """Pide un enlace de acceso a un taller. Responde siempre lo mismo (RF-41)."""
    email = normalize_email(str(body.email))
    await limit_portal_link(request, email)
    # Sin SMTP no hay enlaces: se emitirían sin llegar a nadie.
    if email_sender.enabled:
        background.add_task(_send_link, body.workshop_id, email, email_sender)


@router.post("/auth/consume", status_code=status.HTTP_204_NO_CONTENT)
async def consume_link(body: PortalLinkConsume, request: Request) -> None:
    """Cambia un enlace por una sesión del portal de su taller."""
    await limit_portal_consume(request)
    login = await portal_auth_service.consume(body.workshop_id, body.token)
    await create_client_session(request, login)
