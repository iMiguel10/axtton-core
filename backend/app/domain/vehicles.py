"""Reglas puras de los vehículos (RF-11). Sin I/O."""

import re
from enum import StrEnum


class Fuel(StrEnum):
    GASOLINE = "gasoline"
    DIESEL = "diesel"
    HYBRID = "hybrid"
    PLUG_IN_HYBRID = "plug_in_hybrid"
    ELECTRIC = "electric"
    LPG = "lpg"
    CNG = "cng"
    OTHER = "other"


_SEPARATORS = re.compile(r"[\s\-.·]")
_PLATE = re.compile(r"[A-Z0-9]{1,15}")
# Un VIN moderno tiene 17 caracteres sin I, O ni Q; los anteriores a 1981 son
# más cortos y no siguen la norma, así que solo se exige que sea alfanumérico.
_VIN = re.compile(r"[A-Z0-9]{1,17}")


def normalize_plate(plate: str) -> str:
    """Mayúsculas, sin espacios, guiones ni puntos (RF-11): "1234-bcd",
    "1234 BCD" y "1234BCD" son la misma matrícula."""
    return _SEPARATORS.sub("", plate).upper()


def is_valid_plate(normalized: str) -> bool:
    return _PLATE.fullmatch(normalized) is not None


def normalize_vin(vin: str) -> str:
    return _SEPARATORS.sub("", vin).upper()


def is_valid_vin(normalized: str) -> bool:
    return _VIN.fullmatch(normalized) is not None
