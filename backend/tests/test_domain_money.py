from decimal import Decimal

from app.domain.money import format_eur, format_quantity, format_vat


def test_format_eur_uses_spanish_separators() -> None:
    assert format_eur(10346) == "103,46 €"
    assert format_eur(123456789) == "1.234.567,89 €"
    assert format_eur(5) == "0,05 €"
    assert format_eur(-150) == "-1,50 €"


def test_format_quantity_drops_useless_zeros() -> None:
    assert format_quantity(Decimal("1.000")) == "1"
    assert format_quantity(Decimal("2.500")) == "2,5"
    assert format_quantity(Decimal(10)) == "10"


def test_format_vat_from_basis_points() -> None:
    assert format_vat(2100) == "21 %"
    assert format_vat(1050) == "10,5 %"
    assert format_vat(0) == "0 %"
