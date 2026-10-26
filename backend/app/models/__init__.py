"""Importa todos los modelos para que queden registrados en Base.metadata."""

from app.models.operations import Client
from app.models.platform import (
    AuditEntry,
    Employee,
    Invitation,
    SuperadminInvitation,
    User,
    Workshop,
)

__all__ = [
    "AuditEntry",
    "Client",
    "Employee",
    "Invitation",
    "SuperadminInvitation",
    "User",
    "Workshop",
]
