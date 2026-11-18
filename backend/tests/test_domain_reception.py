"""La firma en pantalla como datos (F6 paso 2, `domain/reception.py`): qué se
acepta como firma y el SVG que escribe el servidor, sin base de datos."""

import math
import re

import pytest

from app.domain.reception import (
    MAX_POINTS,
    MAX_STROKES,
    InvalidSignature,
    clean_signature,
    signature_svg,
)

GOOD: list[list[list[float]]] = [[[10.04, 20], [40, 25.06]], [[100, 30]]]


def test_a_signature_is_rounded_and_kept_in_its_frame() -> None:
    assert clean_signature(600, 200, GOOD) == {
        "width": 600,
        "height": 200,
        "strokes": [[[10.0, 20], [40, 25.1]], [[100, 30]]],
    }


@pytest.mark.parametrize(
    ("width", "height", "strokes", "reason"),
    [
        (600, 200, [], "strokes"),
        (600, 200, [[]], "empty_stroke"),
        (600, 200, [[[1, 2], [3, 4]]] * (MAX_STROKES + 1), "strokes"),
        (600, 200, [[[1, 2]] * (MAX_POINTS + 1)], "points"),
        (10, 200, GOOD, "frame"),
        (600, 200, [[[1, 2, 3]]], "point"),
        (600, 200, [[[-1, 2], [3, 4]]], "outside"),
        (600, 200, [[[1, 201], [3, 4]]], "outside"),
        (600, 200, [[[math.nan, 2], [3, 4]]], "outside"),
        (600, 200, [[[1, 2], [1, 2]], [[5, 5]]], "blank"),
    ],
)
def test_what_is_not_a_signature(
    width: float, height: float, strokes: list[list[list[float]]], reason: str
) -> None:
    with pytest.raises(InvalidSignature, match=reason):
        clean_signature(width, height, strokes)


def test_the_svg_is_written_only_from_numbers() -> None:
    svg = signature_svg(clean_signature(600, 200, GOOD))
    assert svg.startswith(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 200">'
    )
    assert re.findall(r'd="([^"]*)"', svg) == ["M10 20 L40 25.1", "M100 30 L100 30"]
    # Nada que un navegador o WeasyPrint pudiera ejecutar o ir a buscar.
    assert not re.search(r"script|href|url\(|on\w+=", svg)
