"""Reglas puras de los clientes (RF-10). Sin I/O."""

import re
from enum import StrEnum


class ClientKind(StrEnum):
    INDIVIDUAL = "individual"
    COMPANY = "company"


class Language(StrEnum):
    ES = "es"
    EN = "en"


def normalize_email(email: str) -> str:
    """El email es la llave del portal: en minúsculas, para que "Ana@x.com" y
    "ana@x.com" sean el mismo cliente y el índice único los vea iguales."""
    return email.strip().lower()


def normalize_tax_id(tax_id: str) -> str:
    """NIF en mayúsculas y sin espacios, puntos ni guiones: "12.345.678-z" y
    "12345678Z" son el mismo."""
    return re.sub(r"[\s.\-]", "", tax_id).upper()
