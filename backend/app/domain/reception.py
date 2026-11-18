"""La hoja de recepción (F6, RF-51, RF-52): lo que se anota al recibir el coche
y cómo queda firmada.

Los datos de recepción viven en la orden y se editan mientras haga falta. La
hoja firmada es otra cosa: una fila de `reception_sheets` que nace al firmar,
con la copia congelada de esos datos, y que no cambia nunca (invariante 6).
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any


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


# --- La firma en pantalla (RF-52, arquitectura §7.3) -------------------------------
#
# El navegador no manda una imagen ni un SVG: manda los trazos, cada uno una
# lista de puntos, en el marco del lienzo donde se firmó. El servidor los
# comprueba y los guarda como números; el SVG del PDF lo escribe él a partir de
# ellos (`signature_svg`), así que en la firma no puede viajar ni código ni una
# referencia externa (riesgo de la arquitectura §12).

MIN_FRAME = 50
MAX_FRAME = 4000
MAX_STROKES = 60
MAX_POINTS = 6000


class InvalidSignature(ValueError):
    """La firma no son trazos dentro de su lienzo, o no hay firma."""


def clean_signature(
    width: float, height: float, strokes: list[list[list[float]]]
) -> dict[str, Any]:
    """Los trazos tal como se guardan: comprobados, dentro del lienzo y
    redondeados a la décima de píxel. Lanza `InvalidSignature` si no valen."""
    if not (MIN_FRAME <= width <= MAX_FRAME and MIN_FRAME <= height <= MAX_FRAME):
        raise InvalidSignature("frame")
    if not 1 <= len(strokes) <= MAX_STROKES:
        raise InvalidSignature("strokes")
    if sum(len(stroke) for stroke in strokes) > MAX_POINTS:
        raise InvalidSignature("points")
    cleaned: list[list[list[float]]] = []
    for stroke in strokes:
        if not stroke:
            raise InvalidSignature("empty_stroke")
        points: list[list[float]] = []
        for point in stroke:
            if len(point) != 2:
                raise InvalidSignature("point")
            x, y = point
            # NaN no es menor ni mayor que nada: esta comparación también lo para.
            if not (0 <= x <= width and 0 <= y <= height):
                raise InvalidSignature("outside")
            points.append([round(x, 1), round(y, 1)])
        cleaned.append(points)
    # Unos puntos sueltos no son una firma: al menos un trazo que se mueva.
    if not any(len({tuple(p) for p in stroke}) > 1 for stroke in cleaned):
        raise InvalidSignature("blank")
    return {"width": round(width, 1), "height": round(height, 1), "strokes": cleaned}


def _number(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def signature_svg(signature: Mapping[str, Any]) -> str:
    """El SVG de una firma guardada, escrito solo con sus números."""
    width = float(signature["width"])
    height = float(signature["height"])
    paths = []
    for stroke in signature["strokes"]:
        points = [(float(x), float(y)) for x, y in stroke]
        if len(points) == 1:
            # Un punto: un trazo de longitud cero, que el extremo redondo dibuja.
            points.append(points[0])
        d = "M" + " L".join(f"{_number(x)} {_number(y)}" for x, y in points)
        paths.append(f'<path d="{d}"/>')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg"'
        f' viewBox="0 0 {_number(width)} {_number(height)}">'
        '<g fill="none" stroke="#111" stroke-width="2.5"'
        ' stroke-linecap="round" stroke-linejoin="round">'
        f"{''.join(paths)}</g></svg>"
    )


# La forma de `reception_sheets.snapshot`: si cambia, el PDF tiene que saber
# leer también las hojas firmadas con la anterior (RF-55).
SNAPSHOT_VERSION = 1
