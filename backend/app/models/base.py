"""Base de los modelos de SQLAlchemy (arquitectura §3, convenciones).

Los modelos describen las tablas para que el código las use con tipos. Pero la
fuente de verdad del esquema son las migraciones, escritas a mano porque
--autogenerate no sabe de RLS, políticas ni triggers. `alembic check` (en las
pruebas) avisa si un modelo y la base de datos dejan de coincidir.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Nombres de restricciones e índices predecibles: así una migración puede
# referirse a ellos sin adivinar el nombre que Postgres habría inventado.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Por defecto, SQLAlchemy convierte `datetime` en `timestamp` SIN zona
    # horaria: Postgres guardaría la hora tal cual, sin saber de qué zona es.
    # Con timezone=True es `timestamptz`, que guarda un instante absoluto (UTC)
    # y lo devuelve con su zona (convenciones de la arquitectura).
    type_annotation_map = {datetime: DateTime(timezone=True)}  # noqa: RUF012


class IdMixin:
    id: Mapped[UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )


class CreatedAtMixin:
    # clock_timestamp() y no now(): now() da la misma hora a todas las filas de
    # una transacción (decisión 0001 de Applications Tracker).
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())


class UpdatedAtMixin:
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.clock_timestamp(), onupdate=func.clock_timestamp()
    )


# Bloqueo optimista (RNF-15): cada modelo editable declara
#     version: Mapped[int] = mapped_column(server_default="1")
#     __mapper_args__ = {"version_id_col": version}
# Con eso, SQLAlchemy añade "AND version = <la leída>" a cada UPDATE y sube el
# número. Si otra persona guardó antes, el UPDATE no afecta a ninguna fila y
# SQLAlchemy lanza StaleDataError en lugar de pisar su cambio.
