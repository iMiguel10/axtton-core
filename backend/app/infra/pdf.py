"""Generación de PDF con WeasyPrint y plantillas Jinja2 (arquitectura A9, A14).

Vive en infra/ porque habla con algo externo a la aplicación (una librería
nativa que maqueta). Los services le pasan datos ya preparados; no le pasan
nunca HTML escrito por ellos.
"""

import asyncio
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.concurrency import run_in_threadpool
from weasyprint import HTML  # type: ignore[import-untyped]
from weasyprint.urls import URLFetcher, URLFetchingError  # type: ignore[import-untyped]

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


class NoExternalResources(URLFetcher):  # type: ignore[misc]
    """Fetcher que se niega a cargar cualquier recurso.

    Las plantillas llevan el CSS dentro. Si algún día un dato colara una URL en
    el HTML, WeasyPrint no haría ninguna petición desde el servidor (SSRF).
    """

    def fetch(self, url: str, headers: Any = None) -> Any:
        raise URLFetchingError(f"external resources are not allowed: {url}")


def _render_sync(template: str, context: dict[str, Any]) -> bytes:
    html = _jinja.get_template(template).render(**context)
    pdf: bytes = HTML(string=html, url_fetcher=NoExternalResources()).write_pdf()
    return pdf


async def render_pdf(template: str, context: dict[str, Any]) -> bytes:
    """Maqueta una plantilla de templates/pdf/ y devuelve el PDF.

    WeasyPrint es síncrono y tarda: ejecutado directamente en el event loop,
    bloquearía todas las demás peticiones mientras maqueta. Por eso va a un
    hilo aparte (run_in_threadpool).
    """
    async with _render_slots:
        return await run_in_threadpool(_render_sync, template, context)
