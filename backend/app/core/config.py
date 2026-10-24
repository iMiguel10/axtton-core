from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
