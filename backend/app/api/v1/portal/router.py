"""Portal del cliente, versión F0: sin sesión, con un enlace secreto por presupuesto.

En F4 el portal tendrá sesión (enlace mágico) y estas rutas cambiarán. Lo que se
queda es la forma: el taller viaja en el enlace, se fija para RLS y el secreto
solo sirve dentro de ese taller.
"""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import workshop_transaction
from app.schemas.quotes import DecisionCreate, LineRead, PortalQuoteRead
from app.services import quotes as quote_service

router = APIRouter(prefix="/api/v1/portal", tags=["portal"])


async def portal_session(workshop_id: UUID) -> AsyncIterator[AsyncSession]:
    """Sesión con el taller del enlace fijado para RLS.

    Si alguien cambia el taller de la URL, el token se busca en otro taller y
    no aparece: 404, sin revelar nada.
    """
    async with workshop_transaction([workshop_id]) as session:
        yield session


PortalSession = Annotated[AsyncSession, Depends(portal_session)]


@router.get("/quotes/{workshop_id}/{token}", name="view_quote")
async def view_quote(token: str, session: PortalSession) -> PortalQuoteRead:
    view = await quote_service.view_by_token(session, token)
    return PortalQuoteRead(
        status=view.status,
        total_cents=view.total_cents,
        lines=[
            LineRead(
                description=line.description,
                quantity=line.quantity,
                unit_price_cents=line.unit_price_cents,
                vat_bp=line.vat_bp,
                line_total_cents=line.line_total_cents,
            )
            for line in view.lines
        ],
    )


@router.post(
    "/quotes/{workshop_id}/{token}/decision",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def decide_quote(
    workshop_id: UUID,
    token: str,
    body: DecisionCreate,
    session: PortalSession,
    request: Request,
) -> None:
    await quote_service.decide_by_token(
        session,
        workshop_id,
        token,
        body.outcome,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
