"""Crea un superadministrador (RF-110). Es la única forma: no hay pantalla de alta.

    docker compose exec api python -m app.scripts.create_superadmin ana@example.com

La contraseña se pide por teclado, o se lee de SUPERADMIN_PASSWORD si el comando
corre sin terminal (por ejemplo, en un despliegue automatizado). Nunca va en la
línea de comandos, donde quedaría en el historial del shell.
"""

import asyncio
import getpass
import os
import sys

from sqlalchemy import text
from supertokens_python.recipe.emailpassword.asyncio import sign_up
from supertokens_python.recipe.emailpassword.interfaces import SignUpOkResult

from app.core.supertokens import init_supertokens
from app.platform.db import platform_engine, platform_transaction

MIN_PASSWORD_LENGTH = 12


async def create_superadmin(email: str, password: str) -> None:
    init_supertokens()
    # La función de la receta, no la ruta /api/auth/signup: la ruta está anulada
    # (no hay registro público), la función no pasa por ella.
    result = await sign_up("public", email, password)
    if not isinstance(result, SignUpOkResult):
        raise SystemExit(f"No se pudo crear la cuenta: {result.__class__.__name__}")
    async with platform_transaction() as session:
        await session.execute(
            text(
                "INSERT INTO users (supertokens_user_id, kind) VALUES (:s, 'superadmin')"
            ),
            {"s": result.user.id},
        )
        await session.execute(
            text(
                "INSERT INTO audit_log (actor_user_id, action, target_type)"
                " SELECT id, 'superadmin_created', 'user' FROM users"
                " WHERE supertokens_user_id = :s"
            ),
            {"s": result.user.id},
        )
    await platform_engine.dispose()
    print(f"Superadministrador creado: {email}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python -m app.scripts.create_superadmin <email>")
    password = os.environ.get("SUPERADMIN_PASSWORD") or getpass.getpass("Contraseña: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(
            f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres."
        )
    asyncio.run(create_superadmin(sys.argv[1], password))


if __name__ == "__main__":
    main()
