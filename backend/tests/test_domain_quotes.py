"""Pruebas unitarias de domain/quotes.py: sin base de datos, instantáneas.

Los casos concretos fijan la regla de redondeo (RNF-14) y el reparto del
descuento global (RF-39); las pruebas por propiedades (hypothesis) comprueban,
con miles de presupuestos al azar, que el desglose siempre cuadra con el total.
"""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.quotes import (
    MAX_LINES_PER_VERSION,
    DiscountKind,
    GlobalDiscount,
    Line,
    QuoteRuleError,
    compute,
    split_global_discount,
)


def one(line: Line) -> int:
    return compute([line]).total_cents


# --- Redondeo por línea (RNF-14) -----------------------------------------------


def test_line_total_adds_vat_on_the_rounded_base() -> None:
    # 85,50 € + 21 % = 103,455 € → 103,46 € (0,5 sube)
    assert one(Line(Decimal(1), 8550, 2100)) == 10346


def test_half_cent_rounds_up_not_to_even() -> None:
    # round() de Python daría 2 (redondeo al par): aquí debe dar 3.
    assert one(Line(Decimal("0.5"), 5, 0)) == 3


def test_fractional_quantity_is_rounded_per_line() -> None:
    # 2,5 litros a 12,99 € = 32,475 € → 32,48 € de base; IVA 21 % = 6,8208 → 6,82 €
    assert one(Line(Decimal("2.5"), 1299, 2100)) == 3248 + 682


def test_the_total_is_the_sum_of_rounded_lines() -> None:
    lines = [Line(Decimal(1), 8550, 2100), Line(Decimal("2.5"), 1299, 2100)]
    assert compute(lines).total_cents == 10346 + 3930


def test_a_line_discount_is_rounded_on_the_gross_amount() -> None:
    # 3 × 33,33 € = 99,99 €; 10 % = 9,999 → 10,00 €; neto 89,99 €; IVA 21 % =
    # 18,8979 → 18,90 €.
    totals = compute([Line(Decimal(3), 3333, 2100, discount_bp=1000)])
    (line,) = totals.lines
    assert (line.gross_cents, line.discount_cents, line.taxable_cents) == (
        9999,
        1000,
        8999,
    )
    assert (line.vat_cents, line.total_cents) == (1890, 10889)


def test_an_empty_quote_is_zero() -> None:
    totals = compute([])
    assert (totals.total_cents, totals.vat_breakdown) == (0, ())


# --- Descuento global (RF-39) ----------------------------------------------------


def test_the_global_discount_is_split_in_proportion_to_each_base() -> None:
    # 10 % de 300 € = 30 €: 20 € a la de 200 € y 10 € a la de 100 €.
    totals = compute(
        [Line(Decimal(1), 20000, 2100), Line(Decimal(1), 10000, 1000)],
        GlobalDiscount(DiscountKind.PERCENT, 1000),
    )
    assert totals.subtotal_cents == 30000
    assert totals.global_discount_cents == 3000
    assert [t.global_discount_share_cents for t in totals.lines] == [2000, 1000]
    # Y el desglose por tipo de IVA se hace sobre las bases ya rebajadas.
    assert [(g.vat_bp, g.base_cents, g.vat_cents) for g in totals.vat_breakdown] == [
        (2100, 18000, 3780),
        (1000, 9000, 900),
    ]
    assert totals.total_cents == 18000 + 3780 + 9000 + 900


def test_the_leftover_cent_goes_to_the_line_with_the_largest_amount() -> None:
    # 1 € entre tres líneas iguales: 33 + 33 + 33 y sobra 1 céntimo. Empatan en
    # parte decimal y en importe: va a la primera.
    assert split_global_discount(100, [500, 500, 500]) == [34, 33, 33]
    # Con importes distintos y el mismo resto, a la de mayor importe.
    assert split_global_discount(1, [100, 200]) == [0, 1]


def test_an_amount_discount_larger_than_the_quote_is_refused() -> None:
    with pytest.raises(QuoteRuleError) as error:
        compute(
            [Line(Decimal(1), 1000, 2100)], GlobalDiscount(DiscountKind.AMOUNT, 1001)
        )
    assert error.value.code == "global_discount_exceeds_subtotal"


def test_a_full_global_discount_leaves_everything_at_zero() -> None:
    totals = compute(
        [Line(Decimal(1), 1234, 2100), Line(Decimal(2), 999, 400)],
        GlobalDiscount(DiscountKind.PERCENT, 10_000),
    )
    assert totals.total_cents == 0
    assert all(t.taxable_cents == 0 for t in totals.lines)


# --- Datos que no se pueden calcular ------------------------------------------------


@pytest.mark.parametrize(
    ("line", "code"),
    [
        (Line(Decimal(0), 100, 2100), "invalid_quantity"),
        (Line(Decimal(-1), 100, 2100), "invalid_quantity"),
        (Line(Decimal("1.0005"), 100, 2100), "invalid_quantity"),
        (Line(Decimal("NaN"), 100, 2100), "invalid_quantity"),
        (Line(Decimal(1), -1, 2100), "invalid_price"),
        (Line(Decimal(1), 100, 10_001), "invalid_vat"),
        (Line(Decimal(1), 100, 2100, discount_bp=-1), "invalid_discount"),
        (Line(Decimal(1), 100, 2100, discount_bp=10_001), "invalid_discount"),
    ],
)
def test_invalid_lines_are_refused(line: Line, code: str) -> None:
    with pytest.raises(QuoteRuleError) as error:
        compute([line])
    assert error.value.code == code


def test_more_than_the_line_limit_is_refused() -> None:
    lines = [Line(Decimal(1), 100, 2100)] * (MAX_LINES_PER_VERSION + 1)
    with pytest.raises(QuoteRuleError) as error:
        compute(lines)
    assert error.value.code == "too_many_lines"


# --- Propiedades: el desglose cuadra siempre (RNF-14) --------------------------------

VAT_RATES = st.sampled_from([0, 400, 1000, 2100])
quantities = st.decimals(
    min_value=Decimal("0.001"), max_value=Decimal("9999.999"), places=3
)
lines = st.builds(
    Line,
    quantity=quantities,
    unit_price_cents=st.integers(min_value=0, max_value=10_000_000),
    vat_bp=VAT_RATES,
    discount_bp=st.integers(min_value=0, max_value=10_000),
)
discounts = st.one_of(
    st.none(),
    st.builds(
        GlobalDiscount,
        kind=st.just(DiscountKind.PERCENT),
        value=st.integers(min_value=0, max_value=10_000),
    ),
)


@given(st.lists(lines, max_size=30), discounts)
def test_the_breakdown_always_adds_up_to_the_total(
    quote_lines: list[Line], discount: GlobalDiscount | None
) -> None:
    totals = compute(quote_lines, discount)
    # El descuento global se reparte entero, ni un céntimo de más ni de menos.
    shares = [t.global_discount_share_cents for t in totals.lines]
    assert sum(shares) == totals.global_discount_cents
    # Ninguna base imponible queda negativa.
    assert all(t.taxable_cents >= 0 for t in totals.lines)
    # Base + IVA del desglose = total, y las bases = subtotal − descuento global.
    bases = sum(g.base_cents for g in totals.vat_breakdown)
    vat = sum(g.vat_cents for g in totals.vat_breakdown)
    assert bases + vat == totals.total_cents
    assert bases == totals.subtotal_cents - totals.global_discount_cents
    # Cada línea cuadra consigo misma.
    for t in totals.lines:
        assert (
            t.gross_cents - t.discount_cents - t.global_discount_share_cents
            == t.taxable_cents
        )
        assert t.taxable_cents + t.vat_cents == t.total_cents


@given(
    st.integers(min_value=0, max_value=10**9),
    st.lists(st.integers(min_value=0, max_value=10**8), min_size=1, max_size=200),
)
def test_a_split_never_gives_a_line_more_than_its_base(
    amount: int, bases: list[int]
) -> None:
    amount = min(amount, sum(bases))
    shares = split_global_discount(amount, bases)
    assert sum(shares) == (amount if sum(bases) else 0)
    assert all(0 <= share <= base for share, base in zip(shares, bases, strict=True))


@given(st.lists(lines, min_size=1, max_size=10))
def test_the_same_quote_always_gives_the_same_totals(quote_lines: list[Line]) -> None:
    """RF-55: idéntico para el mismo estado. Sin aleatoriedad ni coma flotante."""
    assert compute(quote_lines) == compute(list(quote_lines))
