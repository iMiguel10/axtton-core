"""La entrega del vehículo y la garantía de la reparación (F6 paso 4, RF-53).

La garantía mínima es de 3 meses o 2.000 km desde la entrega, lo que llegue
antes (RD 1457/1986, art. 16). El plazo mayor de una pieza llegará con el
inventario (F7). Un coche entregado sin reparar no tiene garantía de reparación:
no se reparó nada.
"""

import calendar
from dataclasses import dataclass
from datetime import date

WARRANTY_MONTHS = 3
WARRANTY_KM = 2000


@dataclass(frozen=True)
class Warranty:
    # Hasta ese día incluido, en el calendario del taller.
    until: date
    # Hasta esos km, si se anotaron al entregar.
    until_km: int | None


def add_months(day: date, months: int) -> date:
    """El mismo día unos meses después; si ese mes no lo tiene, el último (el
    30 de noviembre más tres meses es el 28 o el 29 de febrero)."""
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def warranty_of(
    delivered_on: date, delivered_km: int | None, *, unrepaired: bool
) -> Warranty | None:
    """La garantía de una orden entregada el día `delivered_on` (en el
    calendario del taller), con `delivered_km` en el cuentakilómetros."""
    if unrepaired:
        return None
    return Warranty(
        until=add_months(delivered_on, WARRANTY_MONTHS),
        until_km=delivered_km + WARRANTY_KM if delivered_km is not None else None,
    )
