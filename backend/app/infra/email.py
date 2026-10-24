"""Envío de emails (A10). Vive en infra/ porque habla con un sistema externo.

Los services dependen de la interfaz `EmailSender`, no de SMTP: en las pruebas se
sustituye por `InMemoryEmailSender` y se comprueba qué se habría enviado.

F1 envía en la propia petición (los emails de acceso, arquitectura §5). La bandeja
de avisos con reintentos y "nunca dos veces" llega en F5.
"""

from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib

from app.core.config import Settings


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    @property
    def enabled(self) -> bool: ...

    async def send(self, email: Email) -> None: ...


class SmtpEmailSender:
    enabled = True

    def __init__(self, settings: Settings) -> None:
        assert settings.smtp_host is not None
        self._settings = settings

    async def send(self, email: Email) -> None:
        message = EmailMessage()
        message["From"] = self._settings.email_from
        message["To"] = email.to
        message["Subject"] = email.subject
        message.set_content(email.body)
        await aiosmtplib.send(
            message,
            hostname=self._settings.smtp_host,
            port=self._settings.smtp_port,
            username=self._settings.smtp_username,
            password=self._settings.smtp_password,
        )


class DisabledEmailSender:
    """Sin SMTP configurado: no envía nada y lo dice (RNF-32)."""

    enabled = False

    async def send(self, email: Email) -> None:
        return None


@dataclass
class InMemoryEmailSender:
    """Para las pruebas: guarda lo que se habría enviado."""

    sent: list[Email] = field(default_factory=list)
    enabled: bool = True

    async def send(self, email: Email) -> None:
        self.sent.append(email)


def build_email_sender(settings: Settings) -> EmailSender:
    if settings.smtp_host:
        return SmtpEmailSender(settings)
    return DisabledEmailSender()
