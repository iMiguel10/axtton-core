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
from app.models.quotes import Quote, QuoteDecision, QuoteLine
from app.models.settings import LaborRate, WorkshopLogo

__all__ = [
    "AuditEntry",
    "Client",
    "DiagnosisVersion",
    "Employee",
    "InternalNote",
    "Invitation",
    "LaborRate",
    "Quote",
    "QuoteDecision",
    "QuoteLine",
    "SuperadminInvitation",
    "User",
    "Vehicle",
    "VehicleOwnership",
    "WorkEntry",
    "WorkOrder",
    "WorkOrderCounter",
    "WorkOrderStatusChange",
    "Workshop",
    "WorkshopLogo",
]
