"""El inventario del taller (F7, RF-90 a RF-97): reglas puras, sin base de datos.

Una pieza del catálogo es lo que el taller vende o monta (RF-90). Su estado
(nueva, usada, reacondicionada o no específica) es el de RF-38 y lo copian las
líneas de presupuesto; su garantía, si es mayor que la de la reparación, la
copia la pieza usada al montarla (RF-53, F7 paso 6).
"""

from decimal import Decimal

from app.domain.delivery import WARRANTY_MONTHS

# La garantía propia de una pieza, en meses. Solo tiene sentido si supera la de
# la reparación (3 meses, RD 1457/1986): con menos, manda la de la reparación.
# El máximo no es legal: es para que un error al teclear no dé diez siglos.
PART_WARRANTY_MIN_MONTHS = WARRANTY_MONTHS + 1
PART_WARRANTY_MAX_MONTHS = 120

# Cantidades con tres decimales (litros de aceite, arquitectura §3): numeric(10,3).
MAX_QUANTITY = Decimal("9999999.999")
