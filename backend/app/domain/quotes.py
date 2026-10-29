"""Reglas puras de los presupuestos: sin base de datos, sin FastAPI (F3 paso 2).

Aquí vive la **única** regla con la que se calculan los totales (RNF-14). El
service la aplica al enviar una versión y guarda el resultado; desde entonces
nadie vuelve a calcular nada: el portal, el PDF y la exportación leen los mismos
números guardados (RNF-11, invariante 6).

Todo en enteros de céntimos y puntos básicos (RNF-10): 2100 puntos = 21 %. Las
cantidades, en `Decimal` con tres decimales, porque se venden litros de aceite.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

BASIS_POINTS = 10_000  # 2100 puntos básicos = 21 %

# Especificación §10: más indica un uso anómalo, y protegen el PDF y el cálculo.
MAX_LINES_PER_VERSION = 200
MAX_VERSIONS_PER_ORDER = 20


class QuoteStatus(StrEnum):
    """Estado de una versión (especificación §6)."""

    DRAFT = "draft"
    SENT = "sent"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class LineKind(StrEnum):
    LABOR = "labor"
    PART = "part"
    OTHER = "other"


class PartCondition(StrEnum):
    """RF-38: una pieza que no es nueva se marca, y el presupuesto lo enseña."""

    NEW = "new"
    USED = "used"
    RECONDITIONED = "reconditioned"
    NON_SPECIFIC = "non_specific"


class DiscountKind(StrEnum):
    PERCENT = "percent"  # el valor, en puntos básicos
    AMOUNT = "amount"  # el valor, en céntimos


class Outcome(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class QuoteRuleError(ValueError):
    """Unos datos con los que no se puede calcular un presupuesto. `code` es el
    código estable que el service devuelve a la interfaz."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Line:
    quantity: Decimal
    unit_price_cents: int
    vat_bp: int
    # Descuento de la línea, en puntos básicos (RF-39).
    discount_bp: int = 0


@dataclass(frozen=True)
class GlobalDiscount:
    kind: DiscountKind
    value: int


@dataclass(frozen=True)
class LineTotals:
    # Cantidad × precio, redondeado.
    gross_cents: int
    # Lo que quita el descuento de la línea.
    discount_cents: int
    # Lo que le toca del descuento global (RF-39), restado de su base.
    global_discount_share_cents: int
    # La base imponible de la línea: bruto − descuento − su parte del global.
    taxable_cents: int
    vat_cents: int
    # Lo que se guarda en `quote_lines.line_total_cents`.
    total_cents: int


@dataclass(frozen=True)
class VatGroup:
    vat_bp: int
    base_cents: int
    vat_cents: int


@dataclass(frozen=True)
class QuoteTotals:
    lines: tuple[LineTotals, ...]
    # La suma de las líneas con sus descuentos, antes del global: lo que el PDF
    # enseña encima del descuento global, que sale como tal y no repartido.
    subtotal_cents: int
    global_discount_cents: int
    # Desglose por tipo de IVA (RF-30), del tipo más alto al más bajo.
    vat_breakdown: tuple[VatGroup, ...]
    total_cents: int


def round_cents(value: Decimal) -> int:
    """Redondeo "de toda la vida": 0,5 sube. El de Python por defecto (round)
    redondea al par más cercano, y 2,5 céntimos darían 2."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _check_line(line: Line) -> None:
    # numeric(10,3): positiva y con tres decimales como mucho (sin NaN ni infinito).
    quantity = line.quantity
    if (
        not quantity.is_finite()
        or quantity <= 0
        or quantity != quantity.quantize(Decimal("0.001"))
    ):
        raise QuoteRuleError("invalid_quantity")
    if line.unit_price_cents < 0:
        raise QuoteRuleError("invalid_price")
    if not 0 <= line.discount_bp <= BASIS_POINTS:
        raise QuoteRuleError("invalid_discount")
    if not 0 <= line.vat_bp <= BASIS_POINTS:
        raise QuoteRuleError("invalid_vat")


def _global_amount(discount: GlobalDiscount | None, subtotal: int) -> int:
    if discount is None or discount.value == 0:
        return 0
    if discount.value < 0:
        raise QuoteRuleError("invalid_discount")
    if discount.kind is DiscountKind.PERCENT:
        if discount.value > BASIS_POINTS:
            raise QuoteRuleError("invalid_discount")
        return round_cents(Decimal(subtotal) * discount.value / BASIS_POINTS)
    # Un descuento mayor que el presupuesto daría bases negativas.
    if discount.value > subtotal:
        raise QuoteRuleError("global_discount_exceeds_subtotal")
    return discount.value


def split_global_discount(amount: int, bases: list[int]) -> list[int]:
    """Reparte `amount` céntimos entre las líneas en proporción a su base (RF-39).

    Cada línea recibe primero la parte entera de lo que le toca. Los céntimos que
    sobran del redondeo se dan de uno en uno a las líneas con mayor parte
    decimal y, si empatan, a la de mayor importe (y luego a la primera). Así la
    suma de las partes es exactamente `amount`, y ninguna línea recibe más que su
    base: su base imponible nunca queda negativa. Con un solo céntimo sobrante,
    que es lo normal, va casi siempre a la línea de mayor importe.
    """
    total = sum(bases)
    if amount == 0 or total == 0:
        return [0] * len(bases)
    shares = [amount * base // total for base in bases]
    leftover = amount - sum(shares)
    # Parte decimal de cada reparto, como resto entero (sin coma flotante).
    order = sorted(
        range(len(bases)),
        key=lambda i: (-(amount * bases[i] % total), -bases[i], i),
    )
    for i in order[:leftover]:
        shares[i] += 1
    return shares


def compute(
    lines: list[Line], global_discount: GlobalDiscount | None = None
) -> QuoteTotals:
    """Los totales de una versión, con la regla única de RNF-14:

    1. Por línea: bruto = cantidad × precio, redondeado; su descuento, redondeado
       sobre el bruto; neto = bruto − descuento.
    2. El descuento global se calcula sobre la suma de los netos y se reparte
       entre las líneas (`split_global_discount`).
    3. Por línea: base imponible = neto − su parte del global; IVA redondeado
       sobre esa base.
    4. Se suman las líneas: el desglose por tipo de IVA y el total son sumas de
       números ya redondeados, así que siempre cuadran.
    """
    if len(lines) > MAX_LINES_PER_VERSION:
        raise QuoteRuleError("too_many_lines")
    for line in lines:
        _check_line(line)
    gross = [round_cents(line.quantity * line.unit_price_cents) for line in lines]
    discounts = [
        round_cents(Decimal(g) * line.discount_bp / BASIS_POINTS)
        for g, line in zip(gross, lines, strict=True)
    ]
    nets = [g - d for g, d in zip(gross, discounts, strict=True)]
    subtotal = sum(nets)
    global_cents = _global_amount(global_discount, subtotal)
    shares = split_global_discount(global_cents, nets)

    totals: list[LineTotals] = []
    groups: dict[int, tuple[int, int]] = {}
    for line, g, d, net, share in zip(
        lines, gross, discounts, nets, shares, strict=True
    ):
        taxable = net - share
        vat = round_cents(Decimal(taxable) * line.vat_bp / BASIS_POINTS)
        totals.append(LineTotals(g, d, share, taxable, vat, taxable + vat))
        base_sum, vat_sum = groups.get(line.vat_bp, (0, 0))
        groups[line.vat_bp] = (base_sum + taxable, vat_sum + vat)

    breakdown = tuple(
        VatGroup(vat_bp, base, vat)
        for vat_bp, (base, vat) in sorted(groups.items(), reverse=True)
    )
    return QuoteTotals(
        lines=tuple(totals),
        subtotal_cents=subtotal,
        global_discount_cents=global_cents,
        vat_breakdown=breakdown,
        total_cents=sum(t.total_cents for t in totals),
    )
