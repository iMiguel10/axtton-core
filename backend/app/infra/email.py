"""Envío de emails (A10). Vive en infra/ porque habla con un sistema externo.

Los services dependen de la interfaz `EmailSender`, no de SMTP: en las pruebas se
sustituye por `InMemoryEmailSender` y se comprueba qué se habría enviado.

Un envío que falla dice si es seguro reintentarlo (F5 paso 3, arquitectura §8):
`EmailNotSentError` si con seguridad no salió, `EmailDeliveryUnknownError` si
pudo salir. La bandeja de avisos (F5 paso 4) solo reintenta el primero: es lo
que hace compatibles "reintentar" y "nunca dos veces" (RF-62).
"""

from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from functools import cache
from pathlib import Path
from typing import Protocol

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import Settings, SmtpSecurity
from app.domain.emails import EmailContent

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "email"
# El logotipo va dentro del email (CID), no enlazado: se ve sin cargar nada de
# fuera, también en los clientes que bloquean las imágenes remotas.
LOGO_CID = "logo@axtton"

# Líneas de hasta 998 caracteres, el límite real (RFC 5322), en vez de 78: una
# cabecera sin espacios más larga, como una URL, no se puede doblar, y con el
# límite por defecto Python la codificaría en RFC 2047 sin necesidad. El texto
# con tildes se sigue codificando como debe (heredado de Applications Tracker).
_SMTP_POLICY = policy.SMTP.clone(max_line_length=998)
_SMTPUTF8_POLICY = policy.SMTPUTF8.clone(max_line_length=998)


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
    # Adónde va la respuesta: el email del taller, para que si el cliente
    # contesta le llegue a él y no a la plataforma (RF-68).
    reply_to: str | None = None


class EmailError(Exception):
    """Base de los errores de envío. Ninguno lleva credenciales del SMTP."""


class EmailNotSentError(EmailError):
    """Con seguridad NO salió: falló la conexión, el cifrado, la autenticación,
    el mensaje no era válido o el servidor lo rechazó con un código. Reintentarlo
    es seguro."""


class EmailDeliveryUnknownError(EmailError):
    """No se sabe si salió: la conexión se cortó o expiró mientras se transmitía
    el mensaje o se esperaba la respuesta final. Reintentarlo podría duplicarlo,
    así que no se reintenta (RF-62)."""


@cache
def _templates() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"])
    )


def compose(to: str, content: EmailContent) -> Email:
    """El email entero a partir de su contenido: el texto plano y el HTML con la
    marca de la plataforma y, si es de un taller, su nombre en la cabecera y en
    el remitente, y su dirección de respuesta."""
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
        reply_to=content.reply_to,
    )


class EmailSender(Protocol):
    """Envía un email o lanza un `EmailError` que dice si es seguro reintentarlo.
    `enabled` es False en una instalación sin SMTP (RNF-32)."""

    @property
    def enabled(self) -> bool: ...

    async def send(self, email: Email) -> None: ...


def build_message(email: Email, email_from: str) -> EmailMessage:
    """El mensaje MIME: el texto y, si lo hay, el HTML como alternativa, con el
    logotipo "related" al HTML (que lo pinta con cid:). El remitente lleva el
    nombre del taller si el email es suyo, con la dirección de la plataforma.

    Un salto de línea en el destinatario, el asunto o una cabecera lo rechaza la
    librería estándar con ValueError: así no se pueden inyectar cabeceras."""
    message = EmailMessage()
    name, address = parseaddr(email_from)
    message["From"] = formataddr((email.sender_name or name, address))
    message["To"] = email.to
    message["Subject"] = email.subject
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=address.split("@")[-1] or None)
    if email.reply_to:
        message["Reply-To"] = email.reply_to
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
    """Envío por SMTP, clasificando **dónde** falla (F5 paso 3).

    La conversación va paso a paso (conexión, cifrado y login, MAIL, RCPT, DATA)
    en lugar de con `aiosmtplib.send`, porque la frontera que importa está dentro
    de DATA: lo que falla antes de transmitir el mensaje no salió, y un corte
    mientras se transmite o se espera la respuesta final es ambiguo. Un código de
    error del servidor, en cualquier punto, es un rechazo explícito: no salió.
    Heredado de Applications Tracker (su F9), con sus pruebas.
    """

    enabled = True

    def __init__(
        self,
        *,
        host: str,
        port: int,
        security: SmtpSecurity,
        username: str | None,
        password: str | None,
        email_from: str,
        timeout_seconds: float,
    ) -> None:
        self._host = host
        self._port = port
        self._security = security
        # compose.prod.yml pasa las opcionales vacías: "" no es un usuario.
        self._username = username or None
        self._password = password or None
        self._from = email_from
        self._envelope_sender = parseaddr(email_from)[1]
        self._timeout = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> "SmtpEmailSender":
        assert settings.smtp_host is not None
        return cls(
            host=settings.smtp_host,
            port=settings.smtp_port,
            security=settings.smtp_security,
            username=settings.smtp_username,
            password=settings.smtp_password,
            email_from=settings.email_from,
            timeout_seconds=settings.smtp_timeout_seconds,
        )

    async def send(self, email: Email) -> None:
        try:
            message = build_message(email, self._from)
        except ValueError as exc:
            raise EmailNotSentError(f"mensaje inválido: {exc}") from exc

        client = aiosmtplib.SMTP(
            hostname=self._host,
            port=self._port,
            use_tls=self._security == "tls",
            # False explícito: con None, aiosmtplib intenta STARTTLS por su cuenta
            # si el servidor lo anuncia, y "none" dejaría de significar "none". Y
            # con "starttls", si el servidor no lo ofrece, no se envía en claro.
            start_tls=self._security == "starttls",
            username=self._username,
            password=self._password,
            timeout=self._timeout,
        )

        # Una dirección con caracteres no ASCII (josé@…) solo viaja con la
        # extensión SMTPUTF8 (RFC 6531), y el mensaje va entonces en UTF-8.
        needs_utf8 = not (email.to.isascii() and self._envelope_sender.isascii())
        options = ["SMTPUTF8"] if needs_utf8 else []
        encoding = "utf-8" if needs_utf8 else "ascii"

        try:
            await client.connect()
            # aiosmtplib saluda (EHLO) de forma perezosa, con el primer comando:
            # justo tras conectar, sin login ni STARTTLS, aún no conoce las
            # extensiones del servidor y supports_extension diría que no a todo.
            if client.last_ehlo_response is None:
                await client.ehlo()
            if needs_utf8 and not client.supports_extension("smtputf8"):
                raise aiosmtplib.SMTPNotSupported(
                    "el servidor no admite direcciones con caracteres no ASCII"
                )
            await client.mail(self._envelope_sender, options=options, encoding=encoding)
            await client.rcpt(email.to, encoding=encoding)
        except (aiosmtplib.SMTPException, OSError) as exc:
            client.close()
            raise EmailNotSentError(_describe(exc)) from exc

        try:
            await client.data(
                message.as_bytes(
                    policy=_SMTPUTF8_POLICY if needs_utf8 else _SMTP_POLICY
                )
            )
        except aiosmtplib.SMTPResponseException as exc:
            # El servidor contestó con un código de error, al pedir DATA o al
            # final del mensaje: lo rechazó de forma explícita.
            client.close()
            raise EmailNotSentError(_describe(exc)) from exc
        except (aiosmtplib.SMTPException, OSError) as exc:
            # Corte o timeout con el mensaje en vuelo: puede que el servidor lo
            # aceptara y la confirmación no llegara.
            client.close()
            raise EmailDeliveryUnknownError(_describe(exc)) from exc

        # Entregado. Un fallo al despedirse ya no cambia nada.
        try:
            await client.quit()
        except (aiosmtplib.SMTPException, OSError):
            client.close()


def _describe(exc: Exception) -> str:
    # Solo el tipo y lo que dijo el servidor: nunca la configuración, que lleva
    # la contraseña del SMTP.
    return f"{type(exc).__name__}: {exc}"


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
        return SmtpEmailSender.from_settings(settings)
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
