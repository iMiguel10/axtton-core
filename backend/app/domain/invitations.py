"""Reglas de las invitaciones, compartidas por el alta de talleres (plataforma) y
la gestión de empleados (taller). Sin I/O: el enlace lo construye quien llama."""

from datetime import timedelta
from uuid import UUID

INVITATION_VALIDITY = timedelta(days=7)  # especificación §10


def invitation_path(workshop_id: UUID, token: str) -> str:
    """Página del frontend que abre la invitación. Lleva el taller para que la
    API lo fije en RLS antes de buscar el token."""
    return f"/invitations/{workshop_id}/{token}"


def invitation_email(
    *, employee_name: str, workshop_name: str, link: str, first_admin: bool
) -> tuple[str, str]:
    """(asunto, cuerpo) del email de invitación."""
    role_line = (
        f"Se ha dado de alta el taller «{workshop_name}» y eres su administrador.\n"
        if first_admin
        else f"Te han invitado a trabajar en «{workshop_name}».\n"
    )
    body = (
        f"Hola, {employee_name}:\n\n"
        f"{role_line}"
        "Para activar tu acceso, abre este enlace (caduca en 7 días):\n\n"
        f"{link}\n\n"
        "Si no esperabas este mensaje, ignóralo."
    )
    return f"Te han dado acceso a {workshop_name} en AXTTON CORE", body


def superadmin_invitation_path(token: str) -> str:
    """Página del frontend que abre una invitación de superadministrador. Sin
    taller: es de la plataforma."""
    return f"/superadmin-invitations/{token}"


def superadmin_invitation_email(*, link: str) -> tuple[str, str]:
    """(asunto, cuerpo) del email que invita a ser superadministrador (RF-110)."""
    body = (
        "Hola:\n\n"
        "Te han invitado a ser superadministrador de esta instalación de AXTTON CORE:"
        " darás de alta talleres y gestionarás sus límites, sin acceso a lo que"
        " ocurre dentro de cada uno.\n\n"
        "Para crear tu cuenta, abre este enlace (caduca en 7 días):\n\n"
        f"{link}\n\n"
        "Si no esperabas este mensaje, ignóralo."
    )
    return "Te han invitado a administrar AXTTON CORE", body
