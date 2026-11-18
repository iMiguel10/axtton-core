"""La hoja de recepción firmada (F6, RF-51, RF-52)."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from app.domain.reception import MAX_FRAME, MAX_STROKES, SignatureMethod

# Un punto es [x, y]; los límites del lienzo y del total los comprueba el
# dominio (`clean_signature`), que también rechaza una firma en blanco.
Point = Annotated[list[FiniteFloat], Field(min_length=2, max_length=2)]
Stroke = Annotated[list[Point], Field(min_length=1, max_length=2000)]


class ScreenSignatureIn(BaseModel):
    """Los trazos de la firma, en el marco del lienzo donde se firmó. Nunca
    una imagen ni un SVG (arquitectura §7.3)."""

    width: FiniteFloat = Field(gt=0, le=MAX_FRAME)
    height: FiniteFloat = Field(gt=0, le=MAX_FRAME)
    strokes: list[Stroke] = Field(min_length=1, max_length=MAX_STROKES)


class SignReception(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # La versión de la orden que vio quien firma: si cambió, no se firma (409).
    version: int
    method: SignatureMethod
    # Quién firma en pantalla: el cliente o quien trajo el coche.
    signer_name: str | None = Field(default=None, max_length=200)
    signature: ScreenSignatureIn | None = None


class ReceptionSheetRead(BaseModel):
    """Cómo se firmó, sin la firma ni la copia congelada: esas van al PDF."""

    signed_at: datetime
    signature_method: SignatureMethod
    recorded_by: str
    signer_name: str | None
    # La renuncia al presupuesto que se firmó, la que vale para RF-27.
    quote_waived: bool
    # Si la imagen de la firma ya se borró al vencer su plazo (RF-56).
    signature_purged: bool
