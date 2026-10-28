from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración leída de variables de entorno (en desarrollo, del `.env`).

    Si falta una variable obligatoria, la aplicación no arranca: es mejor fallar
    al levantar que a mitad de una petición.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Rol axtton_app: todo lo que hace la API pasa por RLS (arquitectura §4).
    database_url: str
    # Rol axtton_platform, que se salta RLS. Solo lo usa app/platform/.
    platform_database_url: str
    # Dirección pública por la que el navegador llega a la aplicación. Con un solo
    # dominio (arquitectura §5) la API y el frontend comparten origen, así que es
    # a la vez el dominio de la web y el de la API para SuperTokens, y la base de
    # los enlaces que se envían por email.
    app_url: str = "http://localhost:5173"

    # SuperTokens (arquitectura A4): el core solo se alcanza por la red interna.
    supertokens_connection_uri: str
    supertokens_api_key: str

    # Correo de la plataforma (RF-68). Sin smtp_host no se envía nada y la
    # aplicación funciona igual (RNF-32).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    email_from: str = "AXTTON CORE <no-reply@localhost>"

    # Modo de instalación (RF-111): un solo taller o varios.
    installation_mode: Literal["multi", "single"] = "multi"

    # Límite de peticiones (RNF-06). Sin Valkey configurado, no se limita.
    valkey_url: str | None = None
    rate_limit_enabled: bool = True
    # Proxies propios cuyo X-Forwarded-For es de fiar (IPs o CIDR, por comas).
    trusted_proxies: str = ""

    # Datos de demostración (app/scripts/seed_demo.py): el script BORRA todo, así
    # que solo corre si esto se activa a propósito. En desarrollo y en la demo
    # desplegada, sí; en una instalación real, nunca.
    demo_seed_enabled: bool = False
    # La contraseña de todas las cuentas de la demo; sin ella, la del script.
    demo_password: str | None = None

    # Versión desplegada: la etiqueta de git (vX.Y.Z) sin la "v" y el commit. No
    # se escriben a mano: la CI los pasa al construir la imagen (APP_VERSION y
    # APP_COMMIT, argumentos del Dockerfile). En desarrollo no hay ninguna.
    app_version: str = "dev"
    app_commit: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
