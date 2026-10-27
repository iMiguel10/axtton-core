"""La forma de los emails (RF-68): el HTML con la marca, el texto de respaldo y
el mensaje MIME que sale por SMTP. Lo que dice cada uno se prueba donde se envía
(test_invitations.py, test_employees.py, test_password.py)."""

from email.utils import parseaddr

from app.domain.emails import invitation_email, password_reset_email
from app.infra.email import LOGO_CID, build_message, compose

LINK = "https://taller.example.com/invitations/w/t0k3n"


def test_a_workshop_email_carries_its_name_and_the_platform_address() -> None:
    email = compose(
        "juan@example.com",
        invitation_email(
            employee_name="Juan",
            workshop_name="Talleres Martínez",
            link=LINK,
            first_admin=False,
        ),
    )
    assert email.sender_name == "Talleres Martínez (AXTTON CORE)"
    assert email.html is not None
    assert "Talleres Martínez" in email.html
    assert f'href="{LINK}"' in email.html
    assert f"cid:{LOGO_CID}" in email.html
    # El texto plano lleva lo mismo, enlace incluido, para quien no ve HTML.
    assert LINK in email.body and "Hola, Juan:" in email.body

    message = build_message(email, "AXTTON CORE <no-reply@axtton.example.com>")
    # Entre comillas, porque lleva paréntesis (RFC 5322): se compara ya leído.
    assert parseaddr(message["From"]) == (
        "Talleres Martínez (AXTTON CORE)",
        "no-reply@axtton.example.com",
    )
    # El texto y, como alternativa, el HTML con su logotipo "related".
    assert [part.get_content_type() for part in message.walk()] == [
        "multipart/alternative",
        "text/plain",
        "multipart/related",
        "text/html",
        "image/png",
    ]
    [logo] = [part for part in message.walk() if part.get_content_type() == "image/png"]
    assert logo["Content-ID"] == f"<{LOGO_CID}>"


def test_a_platform_email_keeps_the_platform_sender() -> None:
    email = compose("ana@example.com", password_reset_email(link=LINK))
    assert email.sender_name is None
    message = build_message(email, "AXTTON CORE <no-reply@axtton.example.com>")
    assert message["From"] == "AXTTON CORE <no-reply@axtton.example.com>"


def test_what_the_workshop_writes_is_escaped_in_the_html() -> None:
    """El nombre del taller lo escribe una persona: no puede meter HTML."""
    email = compose(
        "juan@example.com",
        invitation_email(
            employee_name="<b>Juan</b>",
            workshop_name='Taller "<script>"',
            link=LINK,
            first_admin=True,
        ),
    )
    assert email.html is not None
    assert "<script>" not in email.html and "<b>Juan</b>" not in email.html
    assert "&lt;script&gt;" in email.html
