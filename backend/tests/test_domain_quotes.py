"""Pruebas unitarias de domain/quotes.py: sin base de datos, instantáneas."""

from decimal import Decimal

from app.domain.quotes import Line, line_total_cents, quote_total_cents


def test_line_total_adds_vat_on_the_rounded_base() -> None:
    # 85,50 € + 21 % = 103,455 € → 103,46 € (0,5 sube)
    assert line_total_cents(Line(Decimal(1), 8550, 2100)) == 10346


def test_half_cent_rounds_up_not_to_even() -> None:
    # round() de Python daría 2 (redondeo al par): aquí debe dar 3.
    assert line_total_cents(Line(Decimal("0.5"), 5, 0)) == 3


def test_fractional_quantity_is_rounded_per_line() -> None:
    # 2,5 litros a 12,99 € = 32,475 € → 32,48 € de base; IVA 21 % = 6,8208 → 6,82 €
    assert line_total_cents(Line(Decimal("2.5"), 1299, 2100)) == 3248 + 682


def test_quote_total_is_the_sum_of_rounded_lines() -> None:
    lines = [Line(Decimal(1), 8550, 2100), Line(Decimal("2.5"), 1299, 2100)]
    assert quote_total_cents(lines) == 10346 + 3930
