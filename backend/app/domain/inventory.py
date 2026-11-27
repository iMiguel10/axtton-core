"""El inventario del taller (F7, RF-90 a RF-97): reglas puras, sin base de datos.

Una pieza del catálogo es lo que el taller vende o monta (RF-90). Su estado
(nueva, usada, reacondicionada o no específica) es el de RF-38 y lo copian las
líneas de presupuesto; su garantía, si es mayor que la de la reparación, la
copia la pieza usada al montarla (RF-53, F7 paso 6).
"""

from decimal import Decimal
from enum import StrEnum

from app.domain.delivery import WARRANTY_MONTHS

# La garantía propia de una pieza, en meses. Solo tiene sentido si supera la de
# la reparación (3 meses, RD 1457/1986): con menos, manda la de la reparación.
# El máximo no es legal: es para que un error al teclear no dé diez siglos.
PART_WARRANTY_MIN_MONTHS = WARRANTY_MONTHS + 1
PART_WARRANTY_MAX_MONTHS = 120

# Cantidades con tres decimales (litros de aceite, arquitectura §3): numeric(10,3).
MAX_QUANTITY = Decimal("9999999.999")


class MovementKind(StrEnum):
    """Los movimientos del libro de stock (arquitectura §3, RF-91 a RF-93).

    La cantidad lleva el signo: positiva entra, negativa sale.
    """

    # Llega mercancía (RF-91): siempre positiva, con su coste por unidad.
    IN = "in"
    # Una pieza montada en una orden (RF-93, paso 3): siempre negativa.
    OUT = "out"
    # Recuento, rotura o pérdida (RF-92): de cualquier signo, con su motivo.
    ADJUSTMENT = "adjustment"
    # Deshace otro movimiento con la cantidad contraria (RNF-12): nunca se
    # edita ni se borra el original.
    REVERSAL = "reversal"


# Lo que se puede anular a mano desde el historial. Una salida se deshace
# quitando la pieza usada de su orden (paso 3), y una anulación no se anula:
# el error se corrige con un movimiento nuevo.
REVERSIBLE_BY_HAND = frozenset({MovementKind.IN, MovementKind.ADJUSTMENT})


class StockAlert(StrEnum):
    # RF-94: se montó algo cuya entrada aún no se registró. No impide trabajar.
    NEGATIVE = "negative"
    # RF-95: por debajo del mínimo que fijó el taller.
    BELOW_MINIMUM = "below_minimum"


def stock_alert(stock: Decimal, min_stock: Decimal | None) -> StockAlert | None:
    """La incidencia de una pieza que se cuenta, si la tiene. "Por debajo" es
    estrictamente menos: con el mínimo justo, todavía no avisa."""
    if stock < 0:
        return StockAlert.NEGATIVE
    if min_stock is not None and stock < min_stock:
        return StockAlert.BELOW_MINIMUM
    return None


def count_adjustment(counted: Decimal, stock: Decimal) -> Decimal:
    """El ajuste que deja el stock en lo contado (RF-92): lo que falta o sobra."""
    return counted - stock
