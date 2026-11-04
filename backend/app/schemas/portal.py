from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.session import WhoAmI


class PortalEntryRead(BaseModel):
    workshop_name: str


class PortalLinkRequest(BaseModel):
    # El taller de la página de entrada: el enlace solo será de ese taller.
    workshop_id: UUID
    email: EmailStr


class PortalLinkConsume(BaseModel):
    workshop_id: UUID
    # Los de core/tokens.py tienen 43 caracteres; el tope solo evita cuerpos
    # absurdos antes de calcular el hash.
    token: str = Field(min_length=1, max_length=100)


class PortalMe(WhoAmI):
    workshop_id: UUID
    workshop_name: str
    # IANA: las fechas del portal se enseñan en la zona del taller.
    timezone: str
    client_name: str
    language: str
