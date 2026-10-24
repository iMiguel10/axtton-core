"""Reglas del límite de peticiones (RNF-06). Puras, sin I/O.

Formato de la librería `limits`: "<cantidad>/<periodo>". Son valores de partida que
se ajustarán con uso real. Al superarlos se **frena** (hay que esperar), nunca se
bloquea la cuenta: si diez intentos fallidos la bloquearan, cualquiera podría dejar
sin acceso a otra persona sabiendo solo su email.
"""

from dataclasses import dataclass
from enum import StrEnum


class RateKey(StrEnum):
    """Por qué se agrupan las peticiones."""

    IP = "ip"
    EMAIL = "email"
    USER = "user"
    TOKEN = "token"


@dataclass(frozen=True)
class RateRule:
    name: str
    limit: str
    key: RateKey


# Por IP, holgado: el personal de un taller sale a internet con la misma IP y a
# primera hora entran todos a la vez. Lo que frena a quien prueba contraseñas de
# una cuenta concreta es la regla por email.
SIGNIN_PER_IP = RateRule("signin", "30/minute", RateKey.IP)
SIGNIN_PER_EMAIL = RateRule("signin", "10/hour", RateKey.EMAIL)
PASSWORD_RESET_PER_EMAIL = RateRule("password_reset", "3/hour", RateKey.EMAIL)
PASSWORD_RESET_PER_IP = RateRule("password_reset", "10/hour", RateKey.IP)

# Invitaciones (RF-04, RF-07). El token no se puede adivinar, pero aceptar con un
# email que ya tiene cuenta exige su contraseña: es otra vía para probarlas, así
# que se limita por enlace igual que el inicio de sesión por email.
INVITATION_VIEW_PER_IP = RateRule("invitation_view", "60/hour", RateKey.IP)
INVITATION_ACCEPT_PER_IP = RateRule("invitation_accept", "20/hour", RateKey.IP)
INVITATION_ACCEPT_PER_TOKEN = RateRule(
    "invitation_accept", "5/15minutes", RateKey.TOKEN
)

# Cambiar la contraseña con la actual (RF-122) es una vía para adivinarla desde una
# sesión abierta ajena. Cuenta todos los intentos: nadie la cambia cinco veces seguidas.
PASSWORD_CHANGE_PER_USER = RateRule("password_change", "5/15minutes", RateKey.USER)

# Rutas de SuperTokens (POST, bajo /api/auth) y sus reglas. Las atiende su
# middleware, no nuestros endpoints: las limita app/api/auth_rate_limit.py.
AUTH_RULES: dict[str, tuple[RateRule, ...]] = {
    "signin": (SIGNIN_PER_IP, SIGNIN_PER_EMAIL),
    "user/password/reset/token": (PASSWORD_RESET_PER_EMAIL, PASSWORD_RESET_PER_IP),
}
