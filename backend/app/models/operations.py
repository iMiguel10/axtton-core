"""Tablas operativas del taller (F2): clientes, y después vehículos y órdenes.

Siguen la regla del multi-taller (arquitectura §3): workshop_id propio,
UNIQUE (id, workshop_id) para que las hijas puedan apuntar con FK compuestas, y
RLS forzada, que se añade a mano en la migración.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, UpdatedAtMixin


class Client(IdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """Un cliente del taller (RF-10, especificación §4).

    Es de un solo taller: la misma persona en dos talleres son dos clientes. Su
    email, opcional, es el de acceso al portal (F4); sin email no hay portal.
    Nunca se borra: se archiva, y si lo pide, se anonimiza (RF-15) conservando la
    fila para que sus órdenes y presupuestos sigan apuntando a algo.
    """

    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        CheckConstraint("kind IN ('individual', 'company')", name="kind"),
        CheckConstraint("language IN ('es', 'en')", name="language"),
        # El email es la llave del portal: dos clientes del mismo taller con el
        # mismo email harían ambiguo a quién da acceso un enlace mágico (§7.2).
        # Se guarda ya en minúsculas, así que basta un índice sobre la columna.
        Index(
            "uq_clients_workshop_id_email",
            "workshop_id",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
        Index("ix_clients_workshop_id_name", "workshop_id", "name"),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    kind: Mapped[str] = mapped_column(String(20), server_default="individual")
    # Nombre y apellidos, o razón social si es una empresa.
    name: Mapped[str] = mapped_column(String(200))
    tax_id: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(320))
    address: Mapped[str | None] = mapped_column(String(300))
    # Notas internas: nunca salen del taller.
    notes: Mapped[str | None] = mapped_column(String(2000))
    # Idioma de los avisos y del portal.
    language: Mapped[str] = mapped_column(String(2), server_default="es")
    archived_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(server_default="1")

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012
