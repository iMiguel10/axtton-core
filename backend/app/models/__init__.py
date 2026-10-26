"""Importa todos los modelos para que queden registrados en Base.metadata."""

from app.models.operations import (
    Client,
    DiagnosisVersion,
    InternalNote,
    Vehicle,
    VehicleOwnership,
    WorkEntry,
    WorkOrder,
    WorkOrderCounter,
    WorkOrderStatusChange,
)
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
    "DiagnosisVersion",
    "Employee",
    "InternalNote",
    "Invitation",
    "SuperadminInvitation",
    "User",
    "Vehicle",
    "VehicleOwnership",
    "WorkEntry",
    "WorkOrder",
    "WorkOrderCounter",
    "WorkOrderStatusChange",
    "Workshop",
]
