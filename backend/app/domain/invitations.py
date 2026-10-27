"""Reglas de las invitaciones, compartidas por el alta de talleres (plataforma) y
la gestión de empleados (taller). Sin I/O: el enlace lo construye quien llama."""

from datetime import timedelta
from uuid import UUID

INVITATION_VALIDITY = timedelta(days=7)  # especificación §10


def invitation_path(workshop_id: UUID, token: str) -> str:
    """Página del frontend que abre la invitación. Lleva el taller para que la
    API lo fije en RLS antes de buscar el token."""
    return f"/invitations/{workshop_id}/{token}"


def superadmin_invitation_path(token: str) -> str:
    """Página del frontend que abre una invitación de superadministrador. Sin
    taller: es de la plataforma."""
    return f"/superadmin-invitations/{token}"
