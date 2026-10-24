"""Dependencias de infraestructura comunes a los tres prefijos.

La implementación se elige al arrancar (main.py) y aquí solo se entrega; en las
pruebas se sustituye con app.dependency_overrides.
"""

from fastapi import Request

from app.infra.email import EmailSender


def get_email_sender(request: Request) -> EmailSender:
    sender: EmailSender = request.app.state.email_sender
    return sender
