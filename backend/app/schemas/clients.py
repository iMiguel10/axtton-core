from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.domain.clients import ClientKind, Language


class ClientRead(BaseModel):
    id: UUID
    kind: ClientKind
    name: str
    tax_id: str | None
    phone: str
    email: str | None
    address: str | None
    notes: str | None
    language: Language
    archived_at: datetime | None
    # Anonimizado (RF-15): nombre y teléfono vacíos, lo demás nulo, para siempre.
    anonymized_at: datetime | None
    created_at: datetime
    # El cliente la devuelve al editar: es el bloqueo optimista (RNF-15).
    version: int


class ClientCreate(BaseModel):
    # "   " no es un nombre: se recorta antes de comprobar la longitud.
    model_config = ConfigDict(str_strip_whitespace=True)

    kind: ClientKind = ClientKind.INDIVIDUAL
    name: str = Field(min_length=1, max_length=200)
    tax_id: str | None = Field(default=None, max_length=20)
    phone: str = Field(min_length=1, max_length=30)
    email: EmailStr | None = None
    address: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=2000)
    language: Language = Language.ES


class ClientCreated(BaseModel):
    id: UUID


class ClientUpdate(BaseModel):
    """Solo los campos presentes se cambian (exclude_unset al usarlo)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    version: int
    kind: ClientKind | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    tax_id: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, min_length=1, max_length=30)
    email: EmailStr | None = None
    address: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=2000)
    language: Language | None = None

    @model_validator(mode="after")
    def required_fields_are_not_nulled(self) -> "ClientUpdate":
        """Un `null` explícito en un campo obligatorio es un 422, no un 500 de la
        base de datos (lo aprendido en F1 con los empleados). Los opcionales sí
        se pueden vaciar."""
        for field in ("kind", "name", "phone", "language"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} no puede ser null")
        return self


class VersionOnly(BaseModel):
    version: int
