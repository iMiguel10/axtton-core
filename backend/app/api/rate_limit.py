"""Límite de peticiones (RNF-06): las dependencias de nuestros endpoints y el
middleware de las rutas de SuperTokens.

Las rutas /api/auth/* las atiende el middleware de SuperTokens antes que el
router, así que no admiten dependencias de FastAPI: `AuthRateLimitMiddleware` se
coloca por fuera del de SuperTokens y las alcanza primero.
"""

import json
import logging
from typing import Any

from fastapi import Request
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.client_ip import client_ip, parse_trusted_proxies
from app.core.config import get_settings
from app.core.errors import RateLimitedError
from app.domain.rate_limits import (
    AUTH_RULES,
    INVITATION_ACCEPT_PER_IP,
    INVITATION_ACCEPT_PER_TOKEN,
    INVITATION_VIEW_PER_IP,
    RateRule,
)
from app.infra.rate_limit import RateLimitResult, current_rate_limiter

logger = logging.getLogger(__name__)

# Los formularios de /api/auth ocupan unos cientos de bytes. Leer el cuerpo entero
# para buscar el email no debe servir para agotar la memoria.
MAX_AUTH_BODY_BYTES = 64 * 1024


def retry_after_headers(retry_after: int) -> dict[str, str]:
    return {"Retry-After": str(retry_after)}


def rate_limited_response(retry_after: int) -> JSONResponse:
    return JSONResponse(
        {"code": "rate_limited", "retry_after": retry_after},
        status_code=429,
        headers=retry_after_headers(retry_after),
    )


async def hit(rule: RateRule, key: str) -> RateLimitResult:
    result = await current_rate_limiter().hit(
        rule.limit, rule.name, rule.key.value, key
    )
    if not result.allowed:
        # Sin el valor de la clave: puede ser un email.
        logger.info("Límite %s por %s alcanzado", rule.name, rule.key.value)
    return result


async def enforce(rule: RateRule, key: str) -> None:
    result = await hit(rule, key)
    if not result.allowed:
        raise RateLimitedError(result.retry_after)


def request_ip(request: Request) -> str:
    peer = request.client.host if request.client else None
    return client_ip(
        peer,
        request.headers.get("x-forwarded-for"),
        parse_trusted_proxies(get_settings().trusted_proxies),
    )


# --- Dependencias de nuestros endpoints -------------------------------------


async def limit_invitation_view(request: Request) -> None:
    await enforce(INVITATION_VIEW_PER_IP, request_ip(request))


async def limit_invitation_accept(request: Request, token: str) -> None:
    await enforce(INVITATION_ACCEPT_PER_IP, request_ip(request))
    await enforce(INVITATION_ACCEPT_PER_TOKEN, token)


# --- Rutas de SuperTokens ----------------------------------------------------


def rules_for(path: str) -> tuple[RateRule, ...] | None:
    """Las reglas de una ruta de /api/auth, reconociendo sus formas equivalentes.

    SuperTokens atiende la misma operación con barra final (`/api/auth/signin/`),
    con el tenant en la ruta (`/api/auth/public/signin`) y con parámetros de ruta
    (`/api/auth/signin;x`, que su análisis de la URL ignora). Si aquí solo se
    reconociera la forma canónica, bastaría con cambiar la URL para saltarse el
    límite. Se normaliza de más (mayúsculas, barras repetidas): limitar una ruta
    que SuperTokens rechazaría no cuesta nada.
    """
    segments = [
        segment for s in path.lower().split("/") if (segment := s.split(";", 1)[0])
    ]
    if segments[:2] != ["api", "auth"]:
        return None
    rest = segments[2:]
    for candidate in (rest, rest[1:]):
        rules = AUTH_RULES.get("/".join(candidate))
        if rules:
            return rules
    return None


async def _buffer_body(receive: Receive) -> tuple[bytes | None, Receive]:
    """Lee el cuerpo y devuelve un `receive` que lo vuelve a entregar.

    El cuerpo de una petición ASGI se lee una sola vez: si este middleware lo
    consumiera sin más, SuperTokens recibiría un cuerpo vacío. None si supera el
    tamaño máximo.
    """
    messages: list[Message] = []
    size = 0
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] != "http.request":
            break
        size += len(message.get("body", b""))
        if size > MAX_AUTH_BODY_BYTES:
            return None, receive
        if not message.get("more_body", False):
            break
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.request")

    async def replay() -> Message:
        if messages:
            return messages.pop(0)
        return await receive()

    return body, replay


def _email_from(body: bytes) -> str | None:
    try:
        data: Any = json.loads(body)
        fields = data.get("formFields", [])
        email = next(f.get("value") for f in fields if f.get("id") == "email")
    except (ValueError, AttributeError, StopIteration, TypeError):
        return None
    return email.strip().lower() if isinstance(email, str) and email.strip() else None


class AuthRateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        rules = rules_for(scope.get("path", "")) if scope["type"] == "http" else None
        if not rules or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        body, receive = await _buffer_body(receive)
        if body is None:
            await JSONResponse({"code": "payload_too_large"}, status_code=413)(
                scope, receive, send
            )
            return

        headers = Headers(scope=scope)
        peer = scope["client"][0] if scope.get("client") else None
        keys = {
            "ip": client_ip(
                peer,
                headers.get("x-forwarded-for"),
                parse_trusted_proxies(get_settings().trusted_proxies),
            ),
            "email": _email_from(body),
        }
        for rule in rules:
            key = keys[rule.key.value]
            # Sin email en el cuerpo no hay por qué agrupar: SuperTokens rechazará
            # la petición igualmente.
            if key is None:
                continue
            result = await hit(rule, key)
            if not result.allowed:
                await rate_limited_response(result.retry_after)(scope, receive, send)
                return
        await self.app(scope, receive, send)
