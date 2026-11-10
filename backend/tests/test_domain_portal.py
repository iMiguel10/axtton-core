"""Lo que ve el cliente de una orden (especificación §6, RF-42, RF-80). Sin BD."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.portal import ClientOrderStatus, ClientProgress, client_progress
from app.domain.work_orders import WorkOrderStatus

S = WorkOrderStatus
C = ClientOrderStatus

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
ACTIVITY = NOW - timedelta(days=3)
PAST = NOW - timedelta(days=6)
FUTURE = NOW + timedelta(days=2)

# La tabla de la especificación §6, escrita aquí a propósito otra vez: si alguien
# cambia la del código, esta prueba le pregunta si era eso lo que quería.
SPECIFICATION: dict[WorkOrderStatus, ClientOrderStatus | None] = {
    S.RECEIVED: C.IN_REVIEW,
    S.DIAGNOSING: C.IN_REVIEW,
    S.PENDING_APPROVAL: C.AWAITING_RESPONSE,
    S.APPROVED: C.IN_REPAIR,
    S.IN_REPAIR: C.IN_REPAIR,
    S.WAITING_PARTS: C.WAITING_PARTS,
    S.READY: C.READY,
    S.DELIVERED: C.DELIVERED,
    S.CANCELLED: None,
}

NOT_READY = (
    S.RECEIVED,
    S.DIAGNOSING,
    S.PENDING_APPROVAL,
    S.APPROVED,
    S.IN_REPAIR,
    S.WAITING_PARTS,
)


def progress(
    status: WorkOrderStatus,
    *,
    unrepaired: bool = False,
    expected: datetime | None = None,
) -> ClientProgress | None:
    return client_progress(
        status=status,
        unrepaired=unrepaired,
        last_activity_at=ACTIVITY,
        expected_delivery_at=expected,
        now=NOW,
    )


def visible(
    status: WorkOrderStatus,
    *,
    unrepaired: bool = False,
    expected: datetime | None = None,
) -> ClientProgress:
    result = progress(status, unrepaired=unrepaired, expected=expected)
    assert result is not None
    return result


def test_the_specification_decides_every_internal_status() -> None:
    """Un estado nuevo sin decidir qué ve el cliente hace fallar esta prueba."""
    assert set(SPECIFICATION) == set(WorkOrderStatus)


@pytest.mark.parametrize(("status", "expected"), SPECIFICATION.items())
def test_each_internal_status_is_translated(
    status: WorkOrderStatus, expected: ClientOrderStatus | None
) -> None:
    result = progress(status)
    assert (result.status if result else None) == expected


@pytest.mark.parametrize(
    "name", ["received", "diagnosing", "pending_approval", "approved"]
)
def test_the_portal_vocabulary_has_no_internal_only_status(name: str) -> None:
    assert name not in set(ClientOrderStatus)


def test_ready_without_repair_says_so() -> None:
    assert visible(S.READY, unrepaired=True).status is C.READY_UNREPAIRED


def test_delivered_without_repair_is_just_delivered() -> None:
    """La tabla de §6 solo distingue "sin reparar" mientras está listo."""
    assert visible(S.DELIVERED, unrepaired=True).status is C.DELIVERED


def test_a_cancelled_order_is_not_shown_even_with_a_date() -> None:
    assert progress(S.CANCELLED, expected=PAST) is None


# --- RF-80: un estado viejo no se lee como si fuera actual -------------------------


@pytest.mark.parametrize("status", [s for s, c in SPECIFICATION.items() if c])
def test_rf80_always_says_when_it_was_last_updated(status: WorkOrderStatus) -> None:
    assert visible(status).updated_at == ACTIVITY


@pytest.mark.parametrize("status", NOT_READY)
def test_rf80_a_passed_date_without_the_car_ready_is_flagged(
    status: WorkOrderStatus,
) -> None:
    result = visible(status, expected=PAST)
    assert result.delivery_overdue is True
    # El aviso la necesita: "La fecha prevista era el 14 de octubre".
    assert result.expected_delivery_at == PAST


@pytest.mark.parametrize("status", NOT_READY)
def test_rf80_a_future_date_is_shown_without_warning(status: WorkOrderStatus) -> None:
    result = visible(status, expected=FUTURE)
    assert result.delivery_overdue is False
    assert result.expected_delivery_at == FUTURE


def test_rf80_the_very_instant_of_the_date_has_not_passed_yet() -> None:
    assert visible(S.IN_REPAIR, expected=NOW).delivery_overdue is False


@pytest.mark.parametrize("status", NOT_READY)
def test_rf80_no_date_no_warning(status: WorkOrderStatus) -> None:
    result = visible(status)
    assert result.delivery_overdue is False
    assert result.expected_delivery_at is None


@pytest.mark.parametrize("status", [S.READY, S.DELIVERED])
@pytest.mark.parametrize("expected", [PAST, FUTURE])
def test_rf80_once_ready_the_date_no_longer_matters(
    status: WorkOrderStatus, expected: datetime
) -> None:
    """Sin esto, un coche ya listo enseñaría una fecha pasada como si valiera."""
    result = visible(status, expected=expected)
    assert result.delivery_overdue is False
    assert result.expected_delivery_at is None
