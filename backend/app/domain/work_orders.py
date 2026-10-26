"""Reglas puras de las órdenes de trabajo (RF-20, RF-21, especificación §6).

Sin I/O. Las transiciones entre estados llegan en el paso 4 de F2; aquí están los
valores y lo que no depende de ellas.
"""

from enum import StrEnum


class WorkOrderStatus(StrEnum):
    """Estados internos (especificación §6). El portal los traduce (F4)."""

    RECEIVED = "received"
    DIAGNOSING = "diagnosing"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    IN_REPAIR = "in_repair"
    WAITING_PARTS = "waiting_parts"
    READY = "ready"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


# Una orden cerrada solo admite notas internas y su cobro (RF-26).
CLOSED = frozenset({WorkOrderStatus.DELIVERED, WorkOrderStatus.CANCELLED})
OPEN = frozenset(WorkOrderStatus) - CLOSED


class WorkOrderType(StrEnum):
    BREAKDOWN = "breakdown"
    MAINTENANCE = "maintenance"
    ITV = "itv"
    WARRANTY = "warranty"
    BODYWORK = "bodywork"
    OTHER = "other"


class StatusChangeCause(StrEnum):
    """Qué provocó un cambio de estado. Solo `manual` se puede deshacer (§6).

    `opened` es el primer cambio de toda orden (de nada a `received`): con él,
    el estado de la orden es siempre el del último cambio (invariante 5), también
    recién abierta. No estaba en el diseño (arquitectura §3); se añadió en F2.
    """

    OPENED = "opened"
    MANUAL = "manual"
    QUOTE_SENT = "quote_sent"
    QUOTE_DECIDED = "quote_decided"
    QUOTE_CANCELLED = "quote_cancelled"
    UNDO = "undo"


def order_code(year: int, number: int) -> str:
    """El número legible de una orden (RF-21): OT-2026-0042. Con más de 9999
    órdenes en un año, el número simplemente crece (OT-2026-12345)."""
    return f"OT-{year}-{number:04d}"


def sql_in(column: str, values: type[StrEnum]) -> str:
    """El CHECK de un enumerado (arquitectura §3: varchar + CHECK) a partir del
    propio enum, para que la base de datos y el código no se separen."""
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"
