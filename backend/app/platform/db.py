"""Conexión con el rol axtton_platform, que se salta RLS.

Es la única puerta para leer o escribir en varios talleres a la vez
(arquitectura §4, "Las vías que cruzan talleres"). Ningún endpoint de
/workshop ni de /portal importa este módulo.
"""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings

platform_engine = create_async_engine(
    get_settings().platform_database_url, pool_pre_ping=True
)
PlatformSessionFactory = async_sessionmaker(platform_engine, expire_on_commit=False)
