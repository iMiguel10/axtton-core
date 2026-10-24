"""Enlaces secretos (invitaciones; en F4, enlaces mágicos del portal).

Lo que se envía es el token; lo que se guarda, solo su hash. Si alguien lee la
base de datos, no puede usar ningún enlace.
"""

import hashlib
import secrets


def new_token() -> str:
    """43 caracteres aptos para una URL, imposibles de adivinar."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    """sha256 del token. Un token de `secrets` tiene tanta entropía que basta un
    hash rápido; las contraseñas, que son débiles, necesitan algoritmos lentos
    (de eso se encarga SuperTokens)."""
    return hashlib.sha256(token.encode()).digest()
