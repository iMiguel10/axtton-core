"""Envío de emails (A10). Vive en infra/ porque habla con un sistema externo.

Los services dependen de la interfaz `EmailSender`, no de SMTP: en las pruebas se
sustituye por `InMemoryEmailSender` y se comprueba qué se habría enviado.

F1 envía en la propia petición (los emails de acceso, arquitectura §5). La bandeja
de avisos con reintentos y "nunca dos veces" llega en F5.
"""

from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from functools import cache
from pathlib import Path
from typing import Protocol

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import Settings
from app.domain.emails import EmailContent

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "email"
# El logotipo va dentro del email (CID), no enlazado: se ve sin cargar nada de
# fuera, también en los clientes que bloquean las imágenes remotas.
LOGO_CID = "logo@axtton"


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    # El texto plano: lo que leen los clientes sin HTML, y lo que miran las pruebas.
    body: str
    # La versión con la marca (compose); sin ella, el email sale solo en texto.
    html: str | None = None
    # El nombre del remitente si no es la plataforma: "Talleres Martínez
    # (AXTTON CORE)". La dirección es siempre la de la plataforma (RF-68).
    sender_name: str | None = None


@cache
def _templates() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"])
    )


def compose(to: str, content: EmailContent) -> Email:
    """El email entero a partir de su contenido: el texto plano y el HTML con la
    marca de la plataforma y, si es de un taller, su nombre en la cabecera y en
    el remitente. Cuando los talleres tengan logotipo (RF-02, F3), irá aquí."""
    text = "\n\n".join(
        [
            content.greeting,
            *content.paragraphs,
            f"{content.action_label}: {content.action_url}",
            content.footnote,
        ]
    )
    html = (
        _templates()
        .get_template("base.html")
        .render(content=content, logo_cid=LOGO_CID)
    )
    sender = f"{content.workshop_name} (AXTTON CORE)" if content.workshop_name else None
    return Email(
        to=to,
        subject=content.subject,
        body=text,
        html=html,
        sender_name=sender,
    )


class EmailSender(Protocol):
    @property
    def enabled(self) -> bool: ...

    async def send(self, email: Email) -> None: ...


def build_message(email: Email, email_from: str) -> EmailMessage:
    """El mensaje MIME: el texto y, si lo hay, el HTML como alternativa, con el
    logotipo "related" al HTML (que lo pinta con cid:). El remitente lleva el
    nombre del taller si el email es suyo, con la dirección de la plataforma."""
    message = EmailMessage()
    name, address = parseaddr(email_from)
    message["From"] = formataddr((email.sender_name or name, address))
    message["To"] = email.to
    message["Subject"] = email.subject
    message.set_content(email.body)
    if email.html:
        message.add_alternative(email.html, subtype="html")
        html_part = message.get_body(preferencelist=("html",))
        assert html_part is not None
        html_part.add_related(
            (TEMPLATES / "logo-light.png").read_bytes(),
            maintype="image",
            subtype="png",
            cid=f"<{LOGO_CID}>",
            filename="axtton-core.png",
        )
    return message


class SmtpEmailSender:
    enabled = True

    def __init__(self, settings: Settings) -> None:
        assert settings.smtp_host is not None
        self._settings = settings

    async def send(self, email: Email) -> None:
        await aiosmtplib.send(
            build_message(email, self._settings.email_from),
            hostname=self._settings.smtp_host,
            port=self._settings.smtp_port,
            # compose.prod.yml pasa las opcionales vacías: "" no es un usuario.
            username=self._settings.smtp_username or None,
            password=self._settings.smtp_password or None,
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


# El emisor del proceso. Lo fija main.py al arrancar y lo usan tanto los
# endpoints (por dependencia, app/api/deps.py) como los emails de SuperTokens,
# que no pasan por las dependencias de FastAPI. Las pruebas lo sustituyen con
# set_email_sender: así hay un solo sitio que cambiar.
_current_sender: EmailSender = DisabledEmailSender()


def set_email_sender(sender: EmailSender) -> None:
    global _current_sender
    _current_sender = sender


def current_email_sender() -> EmailSender:
    return _current_sender
