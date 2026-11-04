"""Entrar en el portal: la página de cada taller, pedir el enlace y consumirlo
(arquitectura §7.2, decisión 0006).

Son las únicas rutas de /api/v1/portal sin sesión: quien las usa todavía no la
tiene. Por eso no cuelgan del router del portal, que exige el actor cliente, y
la prueba T1 las nombra como excepción (`PUBLIC_ROUTES` en test_auth.py).

Todas llevan el taller, así que van por la política normal: fijan ese taller y
buscan bajo RLS. Ninguna cruza talleres.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status

from app.api.deps import get_email_sender
from app.api.rate_limit import limit_portal_consume, limit_portal_link
from app.core.config import get_settings
from app.core.sessions import create_client_session
from app.domain.clients import normalize_email
from app.infra.email import EmailSender, compose
from app.schemas.portal import PortalEntryRead, PortalLinkConsume, PortalLinkRequest
from app.services import portal_auth as portal_auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/portal", tags=["portal"])


@router.get("/workshops/{workshop_id}")
async def workshop_entry(workshop_id: UUID) -> PortalEntryRead:
    """El taller de una página de entrada (`/portal/login/{taller}`). 404 si no
    existe o está desactivado."""
    entry = await portal_auth_service.entry(workshop_id)
    return PortalEntryRead(workshop_name=entry.workshop_name)


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
