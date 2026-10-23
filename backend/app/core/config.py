from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración leída de variables de entorno (en desarrollo, del `.env`).

    Si falta una variable obligatoria, la aplicación no arranca: es mejor fallar
    al levantar que a mitad de una petición.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # URL con el rol de la aplicación (axtton_app desde el paso 2, arquitectura §4),
    # nunca con el dueño de las tablas.
    database_url: str


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
