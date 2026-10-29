from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.domain.settings import QUOTE_VALIDITY_MAX_DAYS, QUOTE_VALIDITY_MIN_DAYS


class WorkshopSettingsRead(BaseModel):
    name: str
    legal_name: str | None
    tax_id: str | None
    address: str | None
    phone: str | None
    reply_to_email: str | None
    industrial_registry_number: str | None
    default_vat_bp: int
    quote_validity_business_days: int
    mechanics_see_sale_prices: bool
    # Solo lectura: los fija la plataforma.
    timezone: str
    has_logo: bool
    version: int


class WorkshopSettingsUpdate(BaseModel):
    """Solo los campos presentes se cambian (exclude_unset al usarlo)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    version: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, max_length=200)
    tax_id: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=300)
    phone: str | None = Field(default=None, max_length=30)
    reply_to_email: EmailStr | None = None
    industrial_registry_number: str | None = Field(default=None, max_length=50)
    default_vat_bp: int | None = Field(default=None, ge=0, le=10_000)
    # Nunca menos de 12 días hábiles: es el mínimo legal (RF-33).
    quote_validity_business_days: int | None = Field(
        default=None, ge=QUOTE_VALIDITY_MIN_DAYS, le=QUOTE_VALIDITY_MAX_DAYS
    )
    mechanics_see_sale_prices: bool | None = None

    @model_validator(mode="after")
    def required_fields_are_not_nulled(self) -> "WorkshopSettingsUpdate":
        """Un `null` explícito en un campo obligatorio es un 422, no un 500 de la
        base de datos (lo aprendido en F1)."""
        for field in (
            "name",
            "default_vat_bp",
            "quote_validity_business_days",
            "mechanics_see_sale_prices",
        ):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} no puede ser null")
        return self


class LaborRateRead(BaseModel):
    id: UUID
    name: str
    hourly_price_cents: int
    is_default: bool
    archived_at: datetime | None
    version: int


class LaborRateCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    # Hasta 10.000 € la hora: más es un error al teclear.
    hourly_price_cents: int = Field(ge=0, le=1_000_000)
    is_default: bool = False


class LaborRateCreated(BaseModel):
    id: UUID


class LaborRateUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    version: int
    name: str | None = Field(default=None, min_length=1, max_length=100)
    hourly_price_cents: int | None = Field(default=None, ge=0, le=1_000_000)
    is_default: bool | None = None
