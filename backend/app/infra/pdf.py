"""Generación de PDF con WeasyPrint y plantillas Jinja2 (arquitectura A9, A14).

Vive en infra/ porque habla con algo externo a la aplicación (una librería
nativa que maqueta). Los services le pasan datos ya preparados; no le pasan
nunca HTML escrito por ellos.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.concurrency import run_in_threadpool
from weasyprint import HTML  # type: ignore[import-untyped]
from weasyprint.urls import (  # type: ignore[import-untyped]
    URLFetcher,
    URLFetcherResponse,
    URLFetchingError,
)

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "pdf"

# autoescape: todo lo que llega de los datos se escapa. Una descripción como
# "<img src=...>" sale como texto, no como una etiqueta.
_jinja = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(["html"]),
)

# Maquetar consume CPU y memoria. Como mucho dos PDF a la vez por proceso; el
# resto espera su turno en lugar de tumbar el servidor (A14).
_render_slots = asyncio.Semaphore(2)

# Lo único que una plantilla puede cargar: lo que le pasa quien la maqueta, por
# nombre (`<img src="axtton:logo">`), desde memoria.
RESOURCE_SCHEME = "axtton:"


@dataclass(frozen=True)
class Resource:
    content: bytes
    media_type: str


class NoExternalResources(URLFetcher):  # type: ignore[misc]
    """Fetcher que se niega a cargar cualquier recurso de fuera.

    Las plantillas llevan el CSS dentro. Si algún día un dato colara una URL en
    el HTML, WeasyPrint no haría ninguna petición desde el servidor (SSRF), ni
    leería un fichero, ni una URL `data:`. Solo sirve, desde memoria, los
    recursos `axtton:` que se le dan (el logotipo del taller, ya re-dibujado por
    el servidor: decisión 0005).
    """

    def __init__(self, resources: dict[str, Resource] | None = None) -> None:
        super().__init__()
        self._resources = resources or {}

    def fetch(self, url: str, headers: Any = None) -> Any:
        if url.startswith(RESOURCE_SCHEME):
            resource = self._resources.get(url.removeprefix(RESOURCE_SCHEME))
            if resource is not None:
                return URLFetcherResponse(
                    url,
                    body=resource.content,
                    headers={"Content-Type": resource.media_type},
                )
        raise URLFetchingError(f"external resources are not allowed: {url}")


def _render_sync(
    template: str, context: dict[str, Any], resources: dict[str, Resource]
) -> bytes:
    html = _jinja.get_template(template).render(**context)
    fetcher = NoExternalResources(resources)
    pdf: bytes = HTML(string=html, url_fetcher=fetcher).write_pdf()
    return pdf


async def render_pdf(
    template: str,
    context: dict[str, Any],
    resources: dict[str, Resource] | None = None,
) -> bytes:
    """Maqueta una plantilla de templates/pdf/ y devuelve el PDF.

    WeasyPrint es síncrono y tarda: ejecutado directamente en el event loop,
    bloquearía todas las demás peticiones mientras maqueta. Por eso va a un
    hilo aparte (run_in_threadpool).
    """
    async with _render_slots:
        return await run_in_threadpool(_render_sync, template, context, resources or {})
