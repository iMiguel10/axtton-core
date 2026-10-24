"""El fetcher de WeasyPrint no carga recursos externos, aunque el HTML los pida.

Es la segunda defensa contra SSRF: la primera es el autoescape de Jinja, que
impide que un dato se convierta en una etiqueta.
"""

import pytest
from weasyprint import HTML  # type: ignore[import-untyped]
from weasyprint.urls import URLFetchingError  # type: ignore[import-untyped]

from app.infra.pdf import NoExternalResources


def test_fetcher_refuses_any_url() -> None:
    fetcher = NoExternalResources()
    for url in ("http://169.254.169.254/", "file:///etc/passwd", "data:text/plain,x"):
        with pytest.raises(URLFetchingError):
            fetcher.fetch(url)


def test_html_with_an_external_image_still_renders_without_fetching_it() -> None:
    html = '<p>Hola</p><img src="http://169.254.169.254/latest/meta-data">'
    pdf = HTML(string=html, url_fetcher=NoExternalResources()).write_pdf()
    assert pdf.startswith(b"%PDF")
