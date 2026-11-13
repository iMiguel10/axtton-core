"""El contexto de los trabajos: el de SAQ más lo que `worker.py` crea al
arrancar y comparten todos. Declararlo aquí deja a mypy comprobar
`ctx["email_sender"]` en vez de tratar el contexto como un dict."""

from saq.types import Context

from app.infra.email import EmailSender
from app.infra.queue import JobQueue


class WorkerContext(Context, total=False):
    email_sender: EmailSender
    # El despachador encola en ella el envío de lo que reclama.
    job_queue: JobQueue
