"""Ajustes del taller que edita su administrador (F3, RF-02): las tarifas de mano
de obra y el logotipo. Los datos legales viven en `workshops` (models/platform.py).

Siguen la regla del multi-taller (arquitectura §3), con RLS forzada en la
migración 0012settings.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, UpdatedAtMixin


class LaborRate(IdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """Una tarifa de mano de obra por hora con nombre ("Mecánica", "Chapa").

    Una línea de presupuesto copia su nombre y su precio al usarla (RF-38): no la
    referencia, así que cambiar o archivar una tarifa no toca presupuestos ya
    hechos. Por eso se archiva en vez de borrarse: solo para sacarla de la lista.
    """

    __tablename__ = "labor_rates"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        CheckConstraint("hourly_price_cents >= 0", name="hourly_price_cents"),
        # La de por defecto es la que propone una línea nueva: archivada no
        # serviría para eso.
        CheckConstraint(
            "NOT (is_default AND archived_at IS NOT NULL)", name="default_not_archived"
        ),
        # Como mucho una por defecto por taller (RF-02). El service la cambia
        # quitando antes la marca de la anterior; si dos lo hacen a la vez, este
        # índice para al segundo.
        Index(
            "uq_labor_rates_workshop_id_default",
            "workshop_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
        # Dos tarifas vigentes con el mismo nombre no se distinguirían al elegir.
        Index(
            "uq_labor_rates_workshop_id_name",
            "workshop_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    name: Mapped[str] = mapped_column(String(100))
    hourly_price_cents: Mapped[int] = mapped_column(BigInteger)
    is_default: Mapped[bool] = mapped_column(server_default="false")
    archived_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(server_default="1")

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class WorkshopLogo(CreatedAtMixin, UpdatedAtMixin, Base):
    """El logotipo del taller, ya re-codificado como PNG (decisión 0005).

    Es la única imagen que entra en el sistema (excepción acotada a RF-50): la
    sube el administrador, el servidor la vuelve a dibujar con Pillow y solo se
    guarda el resultado. En su propia tabla, y no en `workshops`, para que no
    viaje en cada petición, que lee el taller activo.

    Sin `id`: su clave es el taller y nadie la referencia, como
    `work_order_counters` (arquitectura §3).
    """

    __tablename__ = "workshop_logos"
    __table_args__ = (
        CheckConstraint("media_type = 'image/png'", name="media_type"),
        CheckConstraint("width > 0 AND height > 0", name="size"),
    )

    workshop_id: Mapped[UUID] = mapped_column(
        ForeignKey("workshops.id"), primary_key=True
    )
    content: Mapped[bytes] = mapped_column(LargeBinary)
    media_type: Mapped[str] = mapped_column(String(30), server_default="image/png")
    width: Mapped[int] = mapped_column(SmallInteger)
    height: Mapped[int] = mapped_column(SmallInteger)
