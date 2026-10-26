"""La búsqueda única del mostrador (RF-14): cómo se lee lo que se escribe. Sin I/O.

Una sola caja para matrícula, nombre o teléfono, porque es lo que se pregunta
con el cliente delante. Lo escrito se interpreta de las tres formas a la vez, y
cada una se compara con su columna ya normalizada al guardar.
"""

import re
from dataclasses import dataclass

from app.domain.vehicles import normalize_plate

# Por debajo de esto, "contiene" encuentra casi todo y no ayuda: no se busca.
MIN_TEXT = 2
MIN_PLATE = 2
MIN_DIGITS = 3
# Lo que cabe en un desplegable del mostrador: más es buscar mejor.
MAX_RESULTS = 8


@dataclass(frozen=True)
class SearchTerms:
    # Para el nombre: se normaliza en la base de datos (search_text), igual
    # que la columna, para que coincidan siempre.
    text: str | None
    # Para la matrícula: mayúsculas, sin espacios ni guiones.
    plate: str | None
    # Para el teléfono: solo los dígitos.
    digits: str | None

    @property
    def empty(self) -> bool:
        return self.text is None and self.plate is None and self.digits is None


def terms(query: str) -> SearchTerms:
    query = query.strip()
    plate = normalize_plate(query)
    digits = re.sub(r"\D", "", query)
    return SearchTerms(
        text=query if len(query) >= MIN_TEXT else None,
        plate=plate if len(plate) >= MIN_PLATE else None,
        digits=digits if len(digits) >= MIN_DIGITS else None,
    )
