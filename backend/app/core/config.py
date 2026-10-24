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


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
