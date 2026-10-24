"""Reglas puras de los presupuestos: sin base de datos, sin FastAPI.

Por eso se prueban con pruebas unitarias rápidas y deterministas.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

BASIS_POINTS = 10_000  # 2100 puntos básicos = 21 %


class QuoteStatus(StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    APPROVED = "approved"
    REJECTED = "rejected"


class Outcome(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


# F0: solo los estados de la orden que toca el presupuesto. El ciclo de vida
# completo, con su historial, llega en F2 (especificación §6).
WORK_ORDER_AFTER_SEND = "pendiente_aprobacion"
WORK_ORDER_AFTER_DECISION = {
    Outcome.APPROVED: "aprobada",
    Outcome.REJECTED: "en_diagnostico",
}


@dataclass(frozen=True)
class Line:
    quantity: Decimal
    unit_price_cents: int
    vat_bp: int


def _round_cents(value: Decimal) -> int:
    # Redondeo "de toda la vida": 0,5 sube. El de Python por defecto (round)
    # redondea al par más cercano, y 2,5 céntimos darían 2.
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def line_total_cents(line: Line) -> int:
    """Total de una línea con IVA, en céntimos.

    Regla única de redondeo (RNF-14): se redondea por línea —primero la base,
    después el IVA— y luego se suman las líneas. Hacerlo en otro orden da
    totales que difieren en un céntimo.
    """
    base = _round_cents(line.quantity * line.unit_price_cents)
    vat = _round_cents(Decimal(base) * line.vat_bp / BASIS_POINTS)
    return base + vat


def quote_total_cents(lines: list[Line]) -> int:
    return sum(line_total_cents(line) for line in lines)
