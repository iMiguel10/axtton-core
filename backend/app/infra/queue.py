"""La cola de trabajos (F5, arquitectura §8): SAQ sobre Valkey, detrás de una
interfaz. Heredada de Applications Tracker, con sus trampas.

Los services encolan con `JobQueue`; en las pruebas, `InMemoryJobQueue` registra
lo encolado sin ejecutar nada, y las pruebas llaman a los trabajos a mano.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from redis.exceptions import RedisError
from saq import Queue

from app.core.config import Settings

# Lo que viaja como argumento de un trabajo: solo ids y escalares, nunca
# objetos ni tokens (Valkey guarda los trabajos en disco). El trabajo carga lo
# demás de la base de datos. Un dato personal, solo si hace falta para el trabajo
# (el email del enlace del portal) y con poco `keep_seconds`.
JobArg = str | int | float | bool | None


class QueueUnavailableError(Exception):
    """No se pudo encolar (Valkey caído o inalcanzable)."""


class JobQueue(Protocol):
    async def enqueue(
        self,
        job: str,
        *,
        timeout_seconds: int,
        max_attempts: int,
        key: str | None = None,
        retry_delay_seconds: float = 0.0,
        keep_seconds: int | None = None,
        **kwargs: JobArg,
    ) -> bool:
        """Encola `job` con `kwargs`. `max_attempts` cuenta el primer intento: 1 es
        "nunca se reintenta", y `retry_delay_seconds` es la espera entre uno y
        otro. Con `key`, devuelve False sin encolar si ya hay un trabajo con esa
        clave. `keep_seconds` es cuánto se guarda el trabajo terminado (por
        defecto, lo de SAQ: 10 minutos); uno que lleva un dato personal, poco.
        Lanza QueueUnavailableError si la cola no responde.
        """
        ...


class SaqJobQueue:
    """`JobQueue` sobre SAQ. Traduce nuestros nombres a los suyos."""

    def __init__(self, queue: Queue) -> None:
        self._queue = queue

    async def enqueue(
        self,
        job: str,
        *,
        timeout_seconds: int,
        max_attempts: int,
        key: str | None = None,
        retry_delay_seconds: float = 0.0,
        keep_seconds: int | None = None,
        **kwargs: JobArg,
    ) -> bool:
        options: dict[str, Any] = {
            "timeout": timeout_seconds,
            # En SAQ, `retries` es el número TOTAL de intentos: un trabajo se
            # repite mientras retries > attempts, y attempts ya vale 1 tras el
            # primero. Por eso la interfaz habla de max_attempts.
            "retries": max_attempts,
            "retry_delay": retry_delay_seconds,
        }
        if key is not None:
            options["key"] = key
        if keep_seconds is not None:
            # `ttl` en SAQ: cuánto se guarda en Valkey el trabajo terminado.
            options["ttl"] = keep_seconds
        # SAQ mezcla en el mismo **kwargs las opciones del trabajo y sus
        # argumentos: uno que se llamara `timeout` o `key` se tomaría por una
        # opción. Pasarlos en `kwargs` explícito lo evita.
        try:
            enqueued = await self._queue.enqueue(job, kwargs=dict(kwargs), **options)
        except (RedisError, OSError) as exc:
            raise QueueUnavailableError(f"{type(exc).__name__}: {exc}") from exc
        return enqueued is not None


@dataclass(frozen=True)
class EnqueuedJob:
    job: str
    kwargs: dict[str, JobArg]
    timeout_seconds: int
    max_attempts: int
    key: str | None
    retry_delay_seconds: float = 0.0
    keep_seconds: int | None = None


class InMemoryJobQueue:
    """Para las pruebas: registra lo encolado y no ejecuta nada. Con `fail`,
    responde como una cola caída."""

    def __init__(self, *, fail: bool = False) -> None:
        self.jobs: list[EnqueuedJob] = []
        self.fail = fail

    async def enqueue(
        self,
        job: str,
        *,
        timeout_seconds: int,
        max_attempts: int,
        key: str | None = None,
        retry_delay_seconds: float = 0.0,
        keep_seconds: int | None = None,
        **kwargs: JobArg,
    ) -> bool:
        if self.fail:
            raise QueueUnavailableError("cola de prueba caída")
        if key is not None and any(queued.key == key for queued in self.jobs):
            return False
        self.jobs.append(
            EnqueuedJob(
                job,
                dict(kwargs),
                timeout_seconds,
                max_attempts,
                key,
                retry_delay_seconds,
                keep_seconds,
            )
        )
        return True


class UnavailableJobQueue:
    """Sin VALKEY_URL no hay cola: encolar falla como con Valkey caído, y quien
    encola decide qué hacer (registrarlo, deshacer un reclamo)."""

    async def enqueue(
        self,
        job: str,
        *,
        timeout_seconds: int,
        max_attempts: int,
        key: str | None = None,
        retry_delay_seconds: float = 0.0,
        keep_seconds: int | None = None,
        **kwargs: JobArg,
    ) -> bool:
        raise QueueUnavailableError("sin VALKEY_URL no hay cola de trabajos")


def build_job_queue(settings: Settings) -> JobQueue:
    """La cola de la API. Se crea al arrancar, pero SAQ no conecta con Valkey
    hasta el primer `enqueue`, ya dentro del event loop de la API (trampa
    heredada: lo que crea asyncio queda ligado al primer loop que lo usa)."""
    if not settings.valkey_url:
        return UnavailableJobQueue()
    return SaqJobQueue(Queue.from_url(settings.valkey_url))


# La cola del proceso de la API, como el emisor de correo (infra/email.py): se
# elige al arrancar (main.py) y las pruebas ponen la suya.
_current_queue: JobQueue = UnavailableJobQueue()


def set_job_queue(queue: JobQueue) -> None:
    global _current_queue
    _current_queue = queue


def current_job_queue() -> JobQueue:
    return _current_queue
