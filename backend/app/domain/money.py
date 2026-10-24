"""Cómo se escriben importes, cantidades y porcentajes para una persona.

Los importes viajan siempre como enteros de céntimos (RNF-10); solo se
convierten en texto al final, para mostrarlos.
"""

from decimal import Decimal


def _group_thousands(digits: str) -> str:
    groups: list[str] = []
    while len(digits) > 3:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    groups.insert(0, digits)
    return ".".join(groups)


def format_eur(cents: int) -> str:
    """10346 → "103,46 €"; 123456789 → "1.234.567,89 €" (formato español)."""
    sign = "-" if cents < 0 else ""
    euros, rest = divmod(abs(cents), 100)
    return f"{sign}{_group_thousands(str(euros))},{rest:02d} €"


def format_quantity(quantity: Decimal) -> str:
    """Decimal("1.000") → "1"; Decimal("2.500") → "2,5"."""
    text = format(quantity.normalize(), "f")
    return text.replace(".", ",")


def format_vat(vat_bp: int) -> str:
    """2100 → "21 %"; 1050 → "10,5 %"."""
    return format_quantity(Decimal(vat_bp) / 100) + " %"
