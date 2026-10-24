"""Errores de la aplicación, independientes de HTTP.

Los services los lanzan sin saber nada de FastAPI (no pueden importarlo, CLAUDE.md
§5). main.py los traduce a respuestas HTTP en un único sitio.
"""


class AppError(Exception):
    status_code = 400

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class NotFoundError(AppError):
    # También se usa cuando el recurso existe pero es de otro taller: responder
    # 403 revelaría que existe (RNF-01).
    status_code = 404


class ConflictError(AppError):
    """La petición es válida, pero el estado actual no la permite."""

    status_code = 409
