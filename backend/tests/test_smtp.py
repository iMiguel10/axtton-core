"""El envío SMTP clasifica dónde falla (F5 paso 3, arquitectura §8).

Es la base de "nunca dos veces" (RF-62): lo que con seguridad no salió
(`EmailNotSentError`) se puede reintentar; lo que pudo salir
(`EmailDeliveryUnknownError`), no. Contra un servidor falso que falla justo en
cada punto de la conversación (`tests/fake_smtp.py`), heredado con sus pruebas
de Applications Tracker.
"""

import contextlib
import socket
from email.utils import parseaddr

import pytest

from app.core.config import SmtpSecurity, get_settings
from app.domain.emails import invitation_email
from app.infra.email import (
    DisabledEmailSender,
    Email,
    EmailDeliveryUnknownError,
    EmailNotSentError,
    SmtpEmailSender,
    build_email_sender,
    compose,
)
from tests.fake_smtp import Behavior, FakeSmtpServer

EMAIL = compose(
    "ana@example.com",
    invitation_email(
        employee_name="Ana",
        workshop_name="Talleres Martínez",
        link="https://taller.example.com/invitations/w/t0k3n",
        first_admin=False,
    ),
)


def make_sender(
    port: int,
    *,
    timeout: float = 5,
    security: SmtpSecurity = "none",
    username: str | None = None,
) -> SmtpEmailSender:
    return SmtpEmailSender(
        host="127.0.0.1",
        port=port,
        security=security,
        username=username,
        password="secreto" if username else None,
        email_from="AXTTON CORE <no-reply@axtton.example.com>",
        timeout_seconds=timeout,
    )


@pytest.mark.asyncio
async def test_an_accepted_email_arrives_whole_with_its_headers() -> None:
    reply = Email(
        to="ana@example.com",
        subject="Tu presupuesto",
        body="Texto",
        html="<p>Texto</p>",
        sender_name="Talleres Martínez (AXTTON CORE)",
        reply_to="taller@example.com",
    )
    async with FakeSmtpServer() as server:
        await make_sender(server.port).send(reply)

    [message] = server.messages
    assert server.recipients == ["ana@example.com"]
    assert parseaddr(message["From"]) == (
        "Talleres Martínez (AXTTON CORE)",
        "no-reply@axtton.example.com",
    )
    # RF-68: si el cliente contesta, le llega al taller.
    assert message["Reply-To"] == "taller@example.com"
    assert message["Subject"] == "Tu presupuesto"
    assert message["Date"] is not None
    assert message["Message-ID"].endswith("@axtton.example.com>")


@pytest.mark.asyncio
async def test_the_branded_email_keeps_its_logo_and_its_text() -> None:
    async with FakeSmtpServer() as server:
        await make_sender(server.port).send(EMAIL)

    [message] = server.messages
    assert message["Reply-To"] is None  # la invitación es de la plataforma
    types = [part.get_content_type() for part in message.walk()]
    assert types == [
        "multipart/alternative",
        "text/plain",
        "multipart/related",
        "text/html",
        "image/png",
    ]
    text = message.get_body(preferencelist=("plain",))
    assert text is not None and "Hola, Ana:" in text.get_content()


@pytest.mark.asyncio
async def test_an_unreachable_server_is_not_sent() -> None:
    # Un puerto que se acaba de liberar: nadie escucha en él.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    with pytest.raises(EmailNotSentError):
        await make_sender(port).send(EMAIL)


@pytest.mark.asyncio
@pytest.mark.parametrize("behavior", ["reject_rcpt", "reject_data"])
async def test_an_explicit_rejection_is_not_sent(behavior: Behavior) -> None:
    """Un código de error del servidor, antes o al final de DATA, es un rechazo:
    el mensaje no se aceptó y reintentarlo no puede duplicarlo."""
    async with FakeSmtpServer(behavior) as server:
        with pytest.raises(EmailNotSentError):
            await make_sender(server.port).send(EMAIL)
    assert server.messages == []


@pytest.mark.asyncio
async def test_a_connection_lost_after_data_is_unknown() -> None:
    """B4 en la infraestructura: el mensaje llegó entero y la conexión se cortó
    sin respuesta final. Puede que el servidor lo aceptara."""
    async with FakeSmtpServer("drop_after_data") as server:
        with pytest.raises(EmailDeliveryUnknownError):
            await make_sender(server.port).send(EMAIL)


@pytest.mark.asyncio
async def test_a_timeout_after_data_is_unknown() -> None:
    async with FakeSmtpServer("hang_after_data") as server:
        with pytest.raises(EmailDeliveryUnknownError):
            await make_sender(server.port, timeout=0.5).send(EMAIL)


@pytest.mark.asyncio
async def test_a_server_that_never_greets_is_not_sent_rather_than_unknown() -> None:
    """B5 en la infraestructura: un timeout ANTES de DATA no puede haber
    entregado nada. Tomarlo por desconocido lo perdería sin reintentar."""
    async with FakeSmtpServer("silent") as server:
        with pytest.raises(EmailNotSentError) as raised:
            await make_sender(server.port, timeout=0.5).send(EMAIL)
    assert not isinstance(raised.value, EmailDeliveryUnknownError)


@pytest.mark.asyncio
async def test_a_connection_lost_before_data_is_not_sent() -> None:
    """La frontera contraria a B4: cortada al enviar RCPT, no salió nada."""
    async with FakeSmtpServer("drop_at_rcpt") as server:
        with pytest.raises(EmailNotSentError):
            await make_sender(server.port).send(EMAIL)
    assert server.messages == []


INJECTED = "\r\nBcc: victima@example.com"
LINE_BREAK_EMAILS = {
    "subject": Email(to="ana@example.com", subject=f"Hola{INJECTED}", body="x"),
    "to": Email(to=f"ana@example.com{INJECTED}", subject="Hola", body="x"),
    # Lo escribe una persona: el nombre del taller (RF-02).
    "sender_name": Email(
        to="ana@example.com", subject="Hola", body="x", sender_name=f"Taller{INJECTED}"
    ),
    # También: el email de respuesta del taller (RF-68).
    "reply_to": Email(
        to="ana@example.com",
        subject="Hola",
        body="x",
        reply_to=f"taller@example.com{INJECTED}",
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("field", LINE_BREAK_EMAILS)
async def test_a_line_break_in_a_header_injects_nothing_and_is_not_sent(
    field: str,
) -> None:
    """Un salto de línea no puede añadir cabeceras ni destinatarios, y el fallo
    se clasifica: un error sin clasificar llegaría a la bandeja de avisos como
    una excepción cualquiera."""
    async with FakeSmtpServer() as server:
        with pytest.raises(EmailNotSentError):
            await make_sender(server.port).send(LINE_BREAK_EMAILS[field])
        with contextlib.suppress(EmailNotSentError):
            await make_sender(server.port).send(LINE_BREAK_EMAILS[field])
    assert [r for r in server.recipients if "victima" in r] == []
    assert server.messages == []


@pytest.mark.asyncio
@pytest.mark.parametrize("security", ["starttls", "tls"])
async def test_encryption_is_never_downgraded(security: SmtpSecurity) -> None:
    """Si se pide cifrado y el servidor no lo ofrece (o no habla TLS), no se envía
    en claro: falla sin transmitir nada."""
    async with FakeSmtpServer() as server:
        with pytest.raises(EmailNotSentError):
            await make_sender(server.port, security=security, timeout=2).send(EMAIL)
    assert server.recipients == []
    assert server.messages == []


@pytest.mark.asyncio
async def test_a_login_the_server_does_not_offer_is_not_sent() -> None:
    async with FakeSmtpServer() as server:
        with pytest.raises(EmailNotSentError):
            await make_sender(server.port, username="usuario").send(EMAIL)
    assert server.messages == []


@pytest.mark.asyncio
async def test_a_non_ascii_recipient_travels_with_smtputf8() -> None:
    async with FakeSmtpServer(smtputf8=True) as server:
        await make_sender(server.port).send(
            Email(to="josé@example.com", subject="Hola", body="Texto")
        )
    assert server.recipients == ["josé@example.com"]
    assert len(server.messages) == 1


@pytest.mark.asyncio
async def test_a_non_ascii_recipient_without_smtputf8_is_not_sent() -> None:
    """Sin la extensión, la dirección no se puede transmitir: se clasifica como
    no enviado, no se escapa como un error de codificación."""
    async with FakeSmtpServer() as server:
        with pytest.raises(EmailNotSentError, match="no ASCII"):
            await make_sender(server.port).send(
                Email(to="josé@example.com", subject="Hola", body="Texto")
            )
    assert server.recipients == []


@pytest.mark.asyncio
async def test_an_error_never_carries_the_smtp_password() -> None:
    async with FakeSmtpServer() as server:
        with pytest.raises(EmailNotSentError) as raised:
            await make_sender(server.port, username="usuario").send(EMAIL)
    assert "secreto" not in str(raised.value)


def test_the_sender_follows_the_settings() -> None:
    settings = get_settings()
    configured = build_email_sender(
        settings.model_copy(
            update={"smtp_host": "smtp.example.com", "smtp_security": "tls"}
        )
    )
    assert isinstance(configured, SmtpEmailSender) and configured.enabled
    unconfigured = build_email_sender(settings.model_copy(update={"smtp_host": None}))
    assert isinstance(unconfigured, DisabledEmailSender)
    assert unconfigured.enabled is False
