"""Límite de peticiones (RNF-06), con la librería `limits` sobre Valkey.

Mismo patrón que el correo (`infra/email.py`): una interfaz, una implementación
real y otra que deja pasar todo, elegidas una vez al arrancar. Las pruebas que
prueban el límite ponen la suya con almacén en memoria.
"""

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import Protocol

from limits import RateLimitItem, parse
from limits.aio.strategies import MovingWindowRateLimiter
from limits.storage import storage_from_string

from app.core.config import Settings

logger = logging.getLogger(__name__)

# Tras un fallo del almacén, cuánto tiempo se deja de consultarlo. Sin esta pausa,
# con Valkey caído cada petición esperaría el timeout de conexión.
STORE_RETRY_SECONDS = 30.0


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    # Segundos hasta que vuelva a permitirse (Retry-After). 0 si se permite.
    retry_after: int = 0


ALLOWED = RateLimitResult(allowed=True)


class RateLimiter(Protocol):
    """Cuenta una petición contra una regla ("10/hour") y dice si se permite.

    `identifiers` agrupa las peticiones: la regla, la clase de clave y su valor.
    """

    async def hit(self, limit: str, *identifiers: str) -> RateLimitResult: ...


class DisabledRateLimiter:
    """Deja pasar todo: sin Valkey configurado, o con RATE_LIMIT_ENABLED=false."""

    async def hit(self, limit: str, *identifiers: str) -> RateLimitResult:
        return ALLOWED


@cache
def _parse(limit: str) -> RateLimitItem:
    return parse(limit)


def storage_uri(valkey_url: str) -> str:
    """`redis://valkey:6379/0` → `async+valkey://valkey:6379/0`: el almacén
    asíncrono de `limits` con el cliente oficial de Valkey."""
    scheme, _, rest = valkey_url.partition("://")
    secure = scheme in {"rediss", "valkeys"}
    return f"async+{'valkeys' if secure else 'valkey'}://{rest}"


class LimitsRateLimiter:
    """Ventana deslizante: con ventanas fijas se podría concentrar el doble de
    intentos justo en el cambio de ventana (los últimos de una y los primeros de
    la siguiente).

    Si el almacén falla, **deja pasar** (heredado de Applications Tracker): es mejor
    quedarse un rato sin límite que dejar a todo el mundo sin poder entrar. No lo
    vuelve a consultar hasta pasados `STORE_RETRY_SECONDS`.
    """

    def __init__(
        self, storage: str, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limiter = MovingWindowRateLimiter(storage_from_string(storage))
        self._clock = clock
        self._store_down_until: float | None = None

    async def hit(self, limit: str, *identifiers: str) -> RateLimitResult:
        if self._store_down_until is not None:
            if self._clock() < self._store_down_until:
                return ALLOWED
            self._store_down_until = None
        item = _parse(limit)
        try:
            if await self._limiter.hit(item, *identifiers):
                return ALLOWED
            stats = await self._limiter.get_window_stats(item, *identifiers)
        except Exception:
            self._store_down_until = self._clock() + STORE_RETRY_SECONDS
            logger.warning(
                "Límite de peticiones sin almacén; se deja pasar durante %.0f s",
                STORE_RETRY_SECONDS,
                exc_info=True,
            )
            return ALLOWED
        retry_after = max(1, math.ceil(stats.reset_time - time.time()))
        return RateLimitResult(allowed=False, retry_after=retry_after)


def build_rate_limiter(settings: Settings) -> RateLimiter:
    if not settings.rate_limit_enabled or not settings.valkey_url:
        return DisabledRateLimiter()
    return LimitsRateLimiter(storage_uri(settings.valkey_url))


_current: RateLimiter = DisabledRateLimiter()


def set_rate_limiter(limiter: RateLimiter) -> None:
    global _current
    _current = limiter


def current_rate_limiter() -> RateLimiter:
    return _current
