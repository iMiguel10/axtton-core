"""Qué versión de la API está corriendo: pública y sin sesión.

La interfaz la compara con la suya para avisar de que hay una versión nueva
desplegada, y el despliegue la consulta para comprobar que arrancó la que
acaba de construir. Solo la versión y el commit: nada de la instalación.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter(prefix="/api/v1/meta", tags=["meta"])


class Meta(BaseModel):
    # La última etiqueta publicada (0.3.0) o "dev". Entre dos versiones, la
    # imagen lleva la última etiqueta y el commit dice qué corre exactamente.
    version: str
    commit: str | None
    # El contrato: solo cambia con un cambio incompatible, no con cada versión.
    api: str = "v1"


@router.get("")
async def meta() -> Meta:
    settings = get_settings()
    # Un argumento de build sin valor llega como cadena vacía, no como ausente.
    return Meta(version=settings.app_version, commit=settings.app_commit or None)
