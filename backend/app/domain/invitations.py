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
