"""Respuestas HTTP comunes a los tres prefijos."""

from fastapi import Response


def pdf_response(pdf: bytes, filename: str) -> Response:
    """PDF para ver en el navegador (inline), no como descarga forzada.

    no-store: un presupuesto tiene datos personales; ni el navegador ni un
    proxy intermedio deben guardar copia.
    """
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
