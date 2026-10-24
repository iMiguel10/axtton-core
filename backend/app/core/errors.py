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


class ForbiddenError(AppError):
    """Hay sesión, pero no es de quien puede usar esta ruta (otro actor)."""

    status_code = 403


class ValidationFailedError(AppError):
    """La petición está bien formada pero un valor no se acepta (p. ej. una
    contraseña débil según la política de SuperTokens)."""

    status_code = 422


class ConflictError(AppError):
    """La petición es válida, pero el estado actual no la permite."""

    status_code = 409


class RateLimitedError(AppError):
    """Demasiadas peticiones (RNF-06). `retry_after`, en segundos, va en el cuerpo
    y en la cabecera Retry-After para que la interfaz diga cuánto esperar."""

    status_code = 429

    def __init__(self, retry_after: int) -> None:
        super().__init__("rate_limited")
        self.retry_after = retry_after
