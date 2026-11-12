"""El worker (F5, arquitectura §8): SAQ sobre Valkey, con la misma imagen que la
API y otro comando.

    saq app.worker.settings

Solo cablea: registra los trabajos de `jobs/` y sus tareas programadas. No aplica
migraciones (las aplica solo `api`, en su entrypoint) y se conecta con los mismos
roles que la API: axtton_app para trabajar, axtton_platform solo desde el
planificador (`app/platform/scheduler.py`).
"""

from saq import Queue
from saq.types import Context, SettingsDict

from app.core.config import get_settings
from app.core.db import engine
from app.jobs.maintenance import maintenance_cron_jobs
from app.platform.db import platform_engine

_valkey_url = get_settings().valkey_url
if not _valkey_url:
    raise RuntimeError("El worker necesita VALKEY_URL: ahí vive la cola de SAQ")

# La cola se crea al importar, pero SAQ no la conecta hasta que el worker arranca,
# ya dentro de su event loop (trampa heredada: las primitivas de asyncio quedan
# ligadas al primer loop que las usa).
queue = Queue.from_url(_valkey_url)


async def shutdown(ctx: Context) -> None:
    # Cierra los pools de Postgres al parar, en vez de dejar las conexiones a medias.
    await engine.dispose()
    await platform_engine.dispose()


settings: SettingsDict[Context] = {
    "queue": queue,
    "functions": [],
    # SAQ encola cada pasada con la clave `cron:<función>`: aunque hubiera dos
    # workers, cada una se ejecuta una vez. Aun así, cada tarea es segura si se
    # ejecutara dos veces (borrar lo ya borrado no hace nada).
    "cron_jobs": maintenance_cron_jobs(),
    "shutdown": shutdown,
    "concurrency": 10,
}
