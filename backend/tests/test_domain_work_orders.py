"""El ciclo de vida de la orden, sin base de datos (especificación §6)."""

import pytest

from app.domain.work_orders import (
    LastChange,
    TransitionRefused,
    WorkOrderStatus,
    allowed_transitions,
    transition_for,
    undo_refusal,
)

S = WorkOrderStatus


def refusal(from_: str, to: str, role: str, **kwargs: str | None) -> str | None:
    params = {"no_quote_reason": None, "note": None, **kwargs}
    try:
        transition_for(from_, to, role, **params)  # type: ignore[arg-type]
    except TransitionRefused as refused:
        return refused.code
    return None


@pytest.mark.parametrize(
    ("from_", "to"),
    [
        (S.RECEIVED, S.READY),
        (S.RECEIVED, S.DELIVERED),
        (S.WAITING_PARTS, S.READY),
        (S.READY, S.IN_REPAIR),
        (S.DELIVERED, S.RECEIVED),
        (S.CANCELLED, S.RECEIVED),
        (S.IN_REPAIR, S.CANCELLED),
        # Las del presupuesto no se hacen a mano: las hace el presupuesto (F3).
        (S.DIAGNOSING, S.PENDING_APPROVAL),
        (S.PENDING_APPROVAL, S.APPROVED),
        (S.PENDING_APPROVAL, S.DIAGNOSING),
        (S.IN_REPAIR, S.PENDING_APPROVAL),
    ],
)
def test_transitions_that_do_not_exist(from_: str, to: str) -> None:
    assert refusal(from_, to, "admin", note="x", no_quote_reason="warranty") == (
        "invalid_transition"
    )


@pytest.mark.parametrize(
    ("from_", "to", "extra"),
    [
        (S.APPROVED, S.IN_REPAIR, {}),
        (S.RECEIVED, S.IN_REPAIR, {"no_quote_reason": "warranty"}),
        (S.DIAGNOSING, S.IN_REPAIR, {"no_quote_reason": "fixed_price"}),
        (S.IN_REPAIR, S.WAITING_PARTS, {}),
        (S.WAITING_PARTS, S.IN_REPAIR, {}),
        (S.IN_REPAIR, S.READY, {}),
    ],
)
def test_what_the_mechanic_moves(from_: str, to: str, extra: dict[str, str]) -> None:
    """Especificación §3: en reparación, esperando piezas y lista (desde en
    reparación). Y el administrador, también."""
    assert refusal(from_, to, "mechanic", **extra) is None
    assert refusal(from_, to, "admin", **extra) is None


@pytest.mark.parametrize(
    ("from_", "to"),
    [
        (S.RECEIVED, S.DIAGNOSING),
        (S.DIAGNOSING, S.READY),  # "sin reparar"
        (S.READY, S.DELIVERED),
        (S.RECEIVED, S.CANCELLED),
        (S.DIAGNOSING, S.CANCELLED),
    ],
)
def test_everything_else_is_for_the_admin(from_: str, to: str) -> None:
    assert refusal(from_, to, "mechanic", note="porque sí") == "not_allowed"
    assert refusal(from_, to, "admin", note="porque sí") is None


@pytest.mark.parametrize("from_", [S.RECEIVED, S.DIAGNOSING])
def test_repairing_without_an_approved_quote_needs_the_no_quote_mark(
    from_: str,
) -> None:
    """RF-27: sin presupuesto aprobado, solo si está marcada "sin presupuesto"."""
    assert refusal(from_, S.IN_REPAIR, "admin") == "no_quote_reason_required"


@pytest.mark.parametrize(
    ("from_", "to"),
    [(S.RECEIVED, S.CANCELLED), (S.DIAGNOSING, S.CANCELLED), (S.DIAGNOSING, S.READY)],
)
@pytest.mark.parametrize("note", [None, "", "   "])
def test_cancelling_and_unrepaired_need_a_note(
    from_: str, to: str, note: str | None
) -> None:
    assert refusal(from_, to, "admin", note=note) == "note_required"


def test_only_diagnosing_to_ready_is_unrepaired() -> None:
    assert transition_for(
        S.DIAGNOSING, S.READY, "admin", no_quote_reason=None, note="Nada que reparar"
    ).unrepaired
    assert not transition_for(
        S.IN_REPAIR, S.READY, "admin", no_quote_reason=None, note=None
    ).unrepaired


def test_the_existence_is_checked_before_the_role() -> None:
    """Un cambio imposible es un 409 para todos, no un 403 para el mecánico."""
    assert refusal(S.RECEIVED, S.DELIVERED, "mechanic") == "invalid_transition"


def test_allowed_transitions_depend_on_role_and_on_the_no_quote_mark() -> None:
    def targets(status: str, role: str, no_quote: str | None = None) -> set[str]:
        return {
            t.to_status
            for t in allowed_transitions(status, role, no_quote_reason=no_quote)
        }

    assert targets(S.RECEIVED, "admin") == {S.DIAGNOSING, S.CANCELLED}
    assert targets(S.RECEIVED, "admin", "warranty") == {
        S.DIAGNOSING,
        S.CANCELLED,
        S.IN_REPAIR,
    }
    assert targets(S.RECEIVED, "mechanic") == set()
    assert targets(S.RECEIVED, "mechanic", "warranty") == {S.IN_REPAIR}
    assert targets(S.IN_REPAIR, "mechanic") == {S.WAITING_PARTS, S.READY}
    assert targets(S.DELIVERED, "admin") == set()


@pytest.mark.parametrize(
    ("last", "expected"),
    [
        (LastChange("received", "diagnosing", "manual", False), None),
        (LastChange(None, "received", "opened", False), "cannot_undo_automatic"),
        (
            LastChange("diagnosing", "pending_approval", "quote_sent", False),
            "cannot_undo_automatic",
        ),
        (
            LastChange("pending_approval", "approved", "quote_decided", False),
            "cannot_undo_automatic",
        ),
        # No hay "rehacer": deshacer un deshacer no vuelve atrás.
        (LastChange("diagnosing", "received", "undo", False), "cannot_undo_automatic"),
        # Deshacer "lista" no puede desenviar el email que ya salió.
        (LastChange("in_repair", "ready", "manual", True), "cannot_undo_notified"),
        # Una entregada no se reabre nunca; una cancelada tampoco vuelve.
        (LastChange("ready", "delivered", "manual", False), "cannot_undo_closing"),
        (LastChange("received", "cancelled", "manual", False), "cannot_undo_closing"),
    ],
)
def test_what_can_be_undone(last: LastChange, expected: str | None) -> None:
    assert undo_refusal(last) == expected
