"""Dependencias de infraestructura comunes a los tres prefijos.

La implementación se elige al arrancar (main.py) y aquí solo se entrega; en las
pruebas se sustituye con set_email_sender o con app.dependency_overrides.
"""

from app.infra.email import EmailSender, current_email_sender


def get_email_sender() -> EmailSender:
    return current_email_sender()
