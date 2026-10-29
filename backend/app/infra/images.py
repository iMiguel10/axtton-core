"""Re-codificar el logotipo del taller con Pillow (decisión 0005).

Vive en infra/ porque usa una librería nativa que decodifica datos que vienen de
fuera. Nunca se guarda lo que se subió: se decodifica, se comprueba, se reduce y
se vuelve a dibujar como PNG. Lo que no sea una imagen, o traiga algo más que
píxeles (metadatos, perfiles, un fichero pegado detrás), no sobrevive.
"""

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from app.domain.settings import (
    LOGO_MAX_HEIGHT,
    LOGO_MAX_SOURCE_PIXELS,
    LOGO_MAX_WIDTH,
)

# Solo estos decodificadores: Pillow abre muchos formatos (algunos con historial
# de fallos de seguridad), y un logo solo puede ser uno de estos dos.
_FORMATS = ("PNG", "JPEG")


class InvalidImageError(Exception):
    """Lo subido no es un PNG o JPEG que se pueda usar como logotipo."""


@dataclass(frozen=True)
class Png:
    content: bytes
    width: int
    height: int


def _normalize_sync(data: bytes) -> Png:
    try:
        with Image.open(BytesIO(data), formats=_FORMATS) as image:
            # El tamaño se lee de la cabecera, sin descomprimir: así se rechaza
            # una bomba de descompresión antes de que ocupe memoria.
            width, height = image.size
            if width * height > LOGO_MAX_SOURCE_PIXELS:
                raise InvalidImageError("too_large")
            image.load()
            # RGBA conserva la transparencia de un PNG; un JPEG no la tiene.
            converted = image.convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise InvalidImageError("not_an_image") from error
    converted.thumbnail((LOGO_MAX_WIDTH, LOGO_MAX_HEIGHT), Image.Resampling.LANCZOS)
    out = BytesIO()
    # Sin `pnginfo`: el PNG nuevo no lleva ningún metadato del original.
    converted.save(out, format="PNG", optimize=True)
    return Png(out.getvalue(), converted.width, converted.height)


async def normalize_logo(data: bytes) -> Png:
    """El logo como PNG limpio y reducido. Decodificar es trabajo de CPU: va en
    un hilo aparte para no parar las demás peticiones, como el PDF."""
    return await run_in_threadpool(_normalize_sync, data)
