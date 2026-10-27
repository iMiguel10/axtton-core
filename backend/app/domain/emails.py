"""El contenido de los emails de la plataforma (RF-68), sin su forma.

Aquí se decide qué dice cada email: el saludo, los párrafos, el botón y la nota
del final. Cómo se ve (el HTML con la marca y el texto plano de respaldo) lo
pone infra/email.py. Así las pruebas comprueban las palabras sin depender de
la maqueta, y la maqueta es una sola para todos.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EmailContent:
    subject: str
    greeting: str
    paragraphs: tuple[str, ...]
    # El botón: lo único que se espera que haga quien lo recibe.
    action_label: str
    action_url: str
    # Lo pequeño del final: caducidad, "si no lo esperabas".
    footnote: str
    # El taller que lo envía; None si es de la plataforma (el superadministrador,
    # la recuperación de contraseña). Sale en la cabecera y en el remitente.
    workshop_name: str | None = None


def invitation_email(
    *, employee_name: str, workshop_name: str, link: str, first_admin: bool
) -> EmailContent:
    """La invitación a un taller: al primer administrador o a un empleado."""
    intro = (
        f"Se ha dado de alta el taller {workshop_name} y eres su administrador."
        if first_admin
        else f"Te han invitado a trabajar en {workshop_name}."
    )
    return EmailContent(
        subject=f"Te han dado acceso a {workshop_name} en AXTTON CORE",
        greeting=f"Hola, {employee_name}:",
        paragraphs=(
            intro,
            "Para activar tu acceso, elige tu contraseña desde este enlace.",
        ),
        action_label="Activar mi acceso",
        action_url=link,
        footnote="El enlace caduca en 7 días. Si no esperabas este mensaje, ignóralo.",
        workshop_name=workshop_name,
    )


def superadmin_invitation_email(*, link: str) -> EmailContent:
    """La invitación a ser superadministrador (RF-110)."""
    return EmailContent(
        subject="Te han invitado a administrar AXTTON CORE",
        greeting="Hola:",
        paragraphs=(
            (
                "Te han invitado a ser superadministrador de esta instalación de"
                " AXTTON CORE: darás de alta talleres y gestionarás sus límites,"
                " sin acceso a lo que ocurre dentro de cada uno."
            ),
        ),
        action_label="Crear mi cuenta",
        action_url=link,
        footnote="El enlace caduca en 7 días. Si no esperabas este mensaje, ignóralo.",
    )


def password_reset_email(*, link: str) -> EmailContent:
    """La recuperación de contraseña (RF-121). Es de la plataforma: la misma
    cuenta puede trabajar en varios talleres."""
    return EmailContent(
        subject="Recupera tu contraseña de AXTTON CORE",
        greeting="Hola:",
        paragraphs=(
            "Has pedido cambiar tu contraseña. Elige una nueva desde este enlace.",
        ),
        action_label="Elegir una contraseña nueva",
        action_url=link,
        footnote=(
            "El enlace caduca en una hora y solo sirve una vez. Si no lo has pedido"
            " tú, ignora este mensaje: tu contraseña no cambia."
        ),
    )
