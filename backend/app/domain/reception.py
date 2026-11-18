"""La hoja de recepción (F6, RF-51, RF-52): lo que se anota al recibir el coche
y cómo queda firmada.

Los datos de recepción viven en la orden y se editan mientras haga falta. La
hoja firmada es otra cosa: una fila de `reception_sheets` que nace al firmar,
con la copia congelada de esos datos, y que no cambia nunca (invariante 6).
"""

from enum import StrEnum


class FuelLevel(StrEnum):
    """El nivel de combustible o de carga al recibir el coche, como lo marca un
    resguardo de depósito: por cuartos, con la reserva aparte."""

    RESERVE = "reserve"
    QUARTER = "quarter"
    HALF = "half"
    THREE_QUARTERS = "three_quarters"
    FULL = "full"


class SignatureMethod(StrEnum):
    """Cómo quedó firmada la hoja (RF-52)."""

    # El cliente firmó en la pantalla del taller (tablet o móvil).
    SCREEN = "screen"
    # El administrador marcó "firmada en papel y conforme"; el papel lo guarda
    # el taller.
    PAPER = "paper"
