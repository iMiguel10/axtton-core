"""Importa todos los modelos para que queden registrados en Base.metadata."""

from app.models.platform import AuditEntry, Employee, Invitation, User, Workshop

__all__ = ["AuditEntry", "Employee", "Invitation", "User", "Workshop"]
