"""Configuración del taller activo (RF-02): datos legales, ajustes, logotipo y
tarifas de mano de obra. Solo su administrador (especificación §3)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status

from app.api.v1.workshop.deps import WorkshopContext, require
from app.core.errors import ValidationFailedError
from app.domain.permissions import Action
from app.domain.settings import LOGO_ACCEPTED_TYPES, LOGO_MAX_UPLOAD_BYTES
from app.schemas.clients import VersionOnly
from app.schemas.settings import (
    LaborRateCreate,
    LaborRateCreated,
    LaborRateRead,
    LaborRateUpdate,
    WorkshopSettingsRead,
    WorkshopSettingsUpdate,
)
from app.services import settings as settings_service

router = APIRouter()

Admin = Annotated[WorkshopContext, Depends(require(Action.MANAGE_WORKSHOP_SETTINGS))]


@router.get("/settings")
async def get_settings(workshop: Admin) -> WorkshopSettingsRead:
    row = await settings_service.get_workshop(workshop.session, workshop.workshop_id)
    has_logo = await settings_service.has_logo(workshop.session, workshop.workshop_id)
    fields = set(WorkshopSettingsRead.model_fields) - {"has_logo"}
    return WorkshopSettingsRead(
        **{field: getattr(row, field) for field in fields}, has_logo=has_logo
    )


@router.patch("/settings", status_code=status.HTTP_204_NO_CONTENT)
async def update_settings(body: WorkshopSettingsUpdate, workshop: Admin) -> None:
    await settings_service.update_workshop(
        workshop.session,
        workshop.workshop_id,
        workshop.user_id,
        expected_version=body.version,
        changes=body.model_dump(mode="json", exclude_unset=True, exclude={"version"}),
    )


async def _read_limited(request: Request) -> bytes:
    """El cuerpo, sin pasar de LOGO_MAX_UPLOAD_BYTES aunque mienta el
    Content-Length: se corta al leerlo, no se confía en la cabecera."""
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > LOGO_MAX_UPLOAD_BYTES:
            raise ValidationFailedError("logo_too_large")
    return bytes(data)


@router.put("/settings/logo", status_code=status.HTTP_204_NO_CONTENT)
async def upload_logo(
    request: Request,
    workshop: Admin,
    content_type: Annotated[str, Header()],
) -> None:
    """El cuerpo es la imagen tal cual (image/png o image/jpeg), sin multipart.

    Excepción acotada a RF-50 (decisión 0005): se guarda la versión que dibuja
    el servidor, nunca lo subido.
    """
    if content_type.split(";")[0].strip().lower() not in LOGO_ACCEPTED_TYPES:
        raise ValidationFailedError("invalid_logo")
    data = await _read_limited(request)
    await settings_service.set_logo(
        workshop.session, workshop.workshop_id, workshop.user_id, data
    )


@router.get("/settings/logo")
async def get_logo(workshop: Admin) -> Response:
    logo = await settings_service.get_logo(workshop.session, workshop.workshop_id)
    return Response(
        content=logo.content,
        media_type=logo.media_type,
        # La sesión va por cookie: que ningún proxy lo guarde para otro.
        headers={"Cache-Control": "private, no-store"},
    )


@router.delete("/settings/logo", status_code=status.HTTP_204_NO_CONTENT)
async def delete_logo(workshop: Admin) -> None:
    await settings_service.remove_logo(
        workshop.session, workshop.workshop_id, workshop.user_id
    )


@router.get("/labor-rates")
async def list_labor_rates(
    workshop: Admin, archived: bool = False
) -> list[LaborRateRead]:
    rates = await settings_service.list_labor_rates(workshop.session, archived=archived)
    return [LaborRateRead.model_validate(r, from_attributes=True) for r in rates]


@router.post("/labor-rates", status_code=status.HTTP_201_CREATED)
async def create_labor_rate(body: LaborRateCreate, workshop: Admin) -> LaborRateCreated:
    rate_id = await settings_service.create_labor_rate(
        workshop.session,
        workshop.workshop_id,
        workshop.user_id,
        name=body.name,
        hourly_price_cents=body.hourly_price_cents,
        is_default=body.is_default,
    )
    return LaborRateCreated(id=rate_id)


@router.patch("/labor-rates/{rate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_labor_rate(
    rate_id: UUID, body: LaborRateUpdate, workshop: Admin
) -> None:
    await settings_service.update_labor_rate(
        workshop.session,
        workshop.workshop_id,
        workshop.user_id,
        rate_id,
        expected_version=body.version,
        changes=body.model_dump(exclude_unset=True, exclude={"version"}),
    )


@router.post("/labor-rates/{rate_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
async def archive_labor_rate(rate_id: UUID, body: VersionOnly, workshop: Admin) -> None:
    await settings_service.set_labor_rate_archived(
        workshop.session,
        workshop.workshop_id,
        workshop.user_id,
        rate_id,
        expected_version=body.version,
        archived=True,
    )


@router.post("/labor-rates/{rate_id}/unarchive", status_code=status.HTTP_204_NO_CONTENT)
async def unarchive_labor_rate(
    rate_id: UUID, body: VersionOnly, workshop: Admin
) -> None:
    await settings_service.set_labor_rate_archived(
        workshop.session,
        workshop.workshop_id,
        workshop.user_id,
        rate_id,
        expected_version=body.version,
        archived=False,
    )
