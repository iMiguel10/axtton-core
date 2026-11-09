"""Reglas puras del portal del cliente (F4). Sin I/O."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

# Validez de un enlace mágico (especificación §10): el cliente puede abrir el
# correo un rato después, pero un enlace olvidado en un buzón no debe valer.
LINK_LIFETIME = timedelta(minutes=15)

# Cuánto dura una sesión del portal (RF-47), desde que se entra. SuperTokens solo
# tiene una duración, la misma para el personal, así que esta se comprueba aquí.
SESSION_LIFETIME = timedelta(days=30)


@dataclass(frozen=True)
class PortalLogin:
    """Quién entra en el portal, decidido por el servidor al consumir un enlace.

    Es lo único que `core/sessions.py` acepta para crear una sesión de cliente:
    el taller y el cliente salen del enlace guardado, nunca de la petición.
    """

    workshop_id: UUID
    client_id: UUID
    email: str
    # La cerradura del cliente al consumir el enlace: si sube después, esta sesión
    # no vale, aunque se cree más tarde.
    portal_epoch: int


def access_link(app_url: str, workshop_id: UUID, token: str) -> str:
    """La dirección del enlace que recibe el cliente.

    El token va en el fragmento (`#`), que el navegador nunca envía al servidor:
    no queda en los registros del proxy ni en la cabecera Referer. El taller va en
    la ruta: es el que la API fija para RLS al consumirlo (T5).
    """
    return f"{app_url.rstrip('/')}/portal/access/{workshop_id}#{token}"
