"""Reglas puras de las órdenes de trabajo (RF-20, RF-21, RF-27, especificación §6).

Sin I/O: los valores, qué transiciones manuales existen, quién puede hacer cada
una y qué cambio se puede deshacer. El service las aplica con la orden
bloqueada.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.domain.permissions import Action, can


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


class NoQuoteReason(StrEnum):
    """Por qué se trabaja sin presupuesto aprobado (RF-27)."""

    # El cliente renuncia: la normativa la exige firmada en el resguardo de
    # depósito, así que solo vale con la hoja de recepción firmada (F6).
    WAIVER = "waiver"
    WARRANTY = "warranty"
    FIXED_PRICE = "fixed_price"


class PaymentStatus(StrEnum):
    """El cobro de una orden (RF-28). No es un estado del ciclo de vida (§6):
    una entregada puede estar cobrada o pendiente."""

    PENDING = "pending"
    PAID = "paid"
    # No se cobra (una garantía, un diagnóstico gratuito): sin esto, quedaría
    # para siempre entre las pendientes de cobro (RF-29). Añadido en F2.
    NO_CHARGE = "no_charge"


class PaymentMethod(StrEnum):
    CASH = "cash"
    CARD = "card"
    TRANSFER = "transfer"
    OTHER = "other"


@dataclass(frozen=True)
class Transition:
    """Un cambio de estado que se hace a mano (causa `manual`)."""

    from_status: WorkOrderStatus
    to_status: WorkOrderStatus
    # La acción de la matriz de permisos que lo autoriza (RNF-03).
    action: Action
    # Cancelar y "sin reparar" exigen explicar por qué (§6).
    needs_note: bool = False
    # Ir a reparación sin presupuesto aprobado exige marcarla antes (RF-27).
    needs_no_quote: bool = False
    # "Lista · sin reparar": el diagnóstico no encontró nada o el cliente no
    # quiso repararlo, y el coche sale igualmente por `delivered`.
    unrepaired: bool = False


S = WorkOrderStatus
# Las transiciones manuales de la especificación §6. Las que provoca el
# presupuesto (entrar en `pending_approval` y salir de él) no están: las hace el
# presupuesto en F3, con su propia causa, nunca una persona.
#
# Quién: el mecánico pasa a `in_repair`, `waiting_parts` y `ready` (solo desde
# `in_repair`): Action.MOVE_REPAIR_STATUS, que tienen los dos roles. Todo lo
# demás es del administrador: Action.MANAGE_ORDERS.
TRANSITIONS: tuple[Transition, ...] = (
    Transition(S.RECEIVED, S.DIAGNOSING, Action.MANAGE_ORDERS),
    Transition(S.APPROVED, S.IN_REPAIR, Action.MOVE_REPAIR_STATUS),
    Transition(S.RECEIVED, S.IN_REPAIR, Action.MOVE_REPAIR_STATUS, needs_no_quote=True),
    Transition(
        S.DIAGNOSING, S.IN_REPAIR, Action.MOVE_REPAIR_STATUS, needs_no_quote=True
    ),
    Transition(S.IN_REPAIR, S.WAITING_PARTS, Action.MOVE_REPAIR_STATUS),
    Transition(S.WAITING_PARTS, S.IN_REPAIR, Action.MOVE_REPAIR_STATUS),
    Transition(S.IN_REPAIR, S.READY, Action.MOVE_REPAIR_STATUS),
    Transition(
        S.DIAGNOSING, S.READY, Action.MANAGE_ORDERS, needs_note=True, unrepaired=True
    ),
    Transition(S.READY, S.DELIVERED, Action.MANAGE_ORDERS),
    # Solo para órdenes abiertas por error (§6). Que no tengan trabajos, piezas
    # ni presupuestos enviados lo comprueba el service, que sabe contarlos.
    Transition(S.RECEIVED, S.CANCELLED, Action.MANAGE_ORDERS, needs_note=True),
    Transition(S.DIAGNOSING, S.CANCELLED, Action.MANAGE_ORDERS, needs_note=True),
)
_BY_STATES = {(t.from_status, t.to_status): t for t in TRANSITIONS}

# Desde estos estados se puede marcar "sin presupuesto": antes de reparar.
NO_QUOTE_STATUSES = frozenset({S.RECEIVED, S.DIAGNOSING})


class TransitionRefused(Exception):
    """Por qué no se puede hacer un cambio. `code` es el código de error de la
    API; el service lo convierte en el error que toca."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def transition_for(
    from_status: str,
    to_status: str,
    role: str,
    *,
    no_quote_reason: str | None,
    note: str | None,
) -> Transition:
    """La transición, si se puede hacer; si no, TransitionRefused con el motivo.

    El orden de las comprobaciones importa: primero si existe (409), luego si
    este rol la puede hacer (403), y por último sus condiciones.
    """
    transition = _BY_STATES.get(
        (WorkOrderStatus(from_status), WorkOrderStatus(to_status))
    )
    if transition is None:
        raise TransitionRefused("invalid_transition")
    if not can(role, transition.action):
        raise TransitionRefused("not_allowed")
    if transition.needs_no_quote and no_quote_reason is None:
        raise TransitionRefused("no_quote_reason_required")
    if transition.needs_note and not (note and note.strip()):
        raise TransitionRefused("note_required")
    return transition


def allowed_transitions(
    from_status: str, role: str, *, no_quote_reason: str | None
) -> list[Transition]:
    """Lo que esta persona puede hacer ahora con la orden, para la interfaz.
    La nota no cuenta: la pide la interfaz al elegir."""
    return [
        t
        for t in TRANSITIONS
        if t.from_status == from_status
        and can(role, t.action)
        and not (t.needs_no_quote and no_quote_reason is None)
    ]


@dataclass(frozen=True)
class LastChange:
    """Lo que hace falta saber del último cambio para decidir si se deshace."""

    from_status: str | None
    to_status: str
    cause: str
    notified: bool


def undo_refusal(last: LastChange) -> str | None:
    """Por qué no se puede deshacer el último cambio, o None si se puede (§6).

    Solo se deshace el último cambio hecho a mano (`manual`): no la apertura, ni
    lo que provocó el presupuesto o el cliente, ni otro deshacer (no hay
    "rehacer": se vuelve a hacer el cambio). Tampoco uno que ya avisó al
    cliente (deshacer "lista" no desenvía el email), ni uno que cerró la orden:
    una orden entregada no se reabre nunca, y una cancelada era un error que ya
    se dio por bueno.
    """
    if last.cause != StatusChangeCause.MANUAL:
        return "cannot_undo_automatic"
    if last.notified:
        return "cannot_undo_notified"
    if last.to_status in CLOSED:
        return "cannot_undo_closing"
    return None


def order_code(year: int, number: int) -> str:
    """El número legible de una orden (RF-21): OT-2026-0042. Con más de 9999
    órdenes en un año, el número simplemente crece (OT-2026-12345)."""
    return f"OT-{year}-{number:04d}"


def sql_in(column: str, values: type[StrEnum]) -> str:
    """El CHECK de un enumerado (arquitectura §3: varchar + CHECK) a partir del
    propio enum, para que la base de datos y el código no se separen."""
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"
