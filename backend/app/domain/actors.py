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


# Lo que lleva además la sesión de un cliente (F4): el taller y el cliente del
# enlace mágico con el que entró. Una sesión de cliente vale para un solo taller.
WORKSHOP_CLAIM = "workshop_id"
CLIENT_CLAIM = "client_id"
# La cerradura del cliente cuando se creó la sesión, y hasta cuándo vale (RF-47).
PORTAL_EPOCH_CLAIM = "portal_epoch"
PORTAL_EXPIRES_CLAIM = "portal_expires_at"
