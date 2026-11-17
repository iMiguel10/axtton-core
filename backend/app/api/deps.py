"""Dependencias de infraestructura comunes a los tres prefijos.

La implementación se elige al arrancar (main.py) y aquí solo se entrega; en las
pruebas se sustituye con set_email_sender o con app.dependency_overrides.
"""

from app.infra.email import EmailSender, current_email_sender
from app.infra.queue import JobQueue, current_job_queue


def get_email_sender() -> EmailSender:
    return current_email_sender()


def get_job_queue() -> JobQueue:
    """La cola del worker (F5): lo que la API deja para que se haga después."""
    return current_job_queue()
