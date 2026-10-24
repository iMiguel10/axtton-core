"""Los tres actores (arquitectura §2): qué tipo de persona ha iniciado sesión.

No confundir con el rol en el taller (admin, mechanic), que vive en employees y
se comprueba en cada petición, ni con los roles de base de datos.
"""

from enum import StrEnum

# Clave del actor dentro del access token de SuperTokens.
ACTOR_CLAIM = "actor"


class Actor(StrEnum):
    STAFF = "staff"
    SUPERADMIN = "superadmin"
    CLIENT = "client"
