"""El inventario del taller (F7, arquitectura §3): el catálogo de piezas.

Sigue la regla del multi-taller, con RLS forzada en la migración 0027parts. Una
pieza no se borra (llegarán sus movimientos de stock y las órdenes que la
montaron): se archiva, y deja de salir al elegir.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.inventory import PART_WARRANTY_MAX_MONTHS, PART_WARRANTY_MIN_MONTHS
from app.domain.quotes import PartCondition
from app.domain.work_orders import sql_in
from app.models.base import Base, CreatedAtMixin, IdMixin, UpdatedAtMixin


class Part(IdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """Una pieza del catálogo (RF-90).

    Una línea de presupuesto copia su descripción, su referencia y su precio al
    elegirla (RF-38): cambiar después el catálogo no cambia lo presupuestado.
    """

    __tablename__ = "parts"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        # La referencia identifica la pieza en el taller, también archivada: en
        # su historial y en las órdenes que la montaron. Sin distinguir
        # mayúsculas: "BAT-70" y "bat-70" son la misma.
        Index(
            "uq_parts_workshop_id_reference",
            "workshop_id",
            text("lower(reference)"),
            unique=True,
        ),
        CheckConstraint("length(btrim(reference)) > 0", name="reference"),
        CheckConstraint("length(btrim(description)) > 0", name="description"),
        CheckConstraint("cost_price_cents >= 0", name="cost_price_cents"),
        CheckConstraint("sale_price_cents >= 0", name="sale_price_cents"),
        CheckConstraint("vat_bp BETWEEN 0 AND 10000", name="vat_bp"),
        CheckConstraint(sql_in("part_condition", PartCondition), name="part_condition"),
        CheckConstraint(
            f"warranty_months BETWEEN {PART_WARRANTY_MIN_MONTHS}"
            f" AND {PART_WARRANTY_MAX_MONTHS}",
            name="warranty_months",
        ),
        # El mínimo solo existe si se cuenta el stock (RF-95).
        CheckConstraint(
            "min_stock IS NULL OR (tracks_stock AND min_stock >= 0)",
            name="min_stock",
        ),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    reference: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(300))
    brand: Mapped[str | None] = mapped_column(String(100))
    # El de coste solo lo ve el administrador (especificación §3); puede no
    # saberse.
    cost_price_cents: Mapped[int | None] = mapped_column(BigInteger)
    # Sin IVA, como las tarifas: el IVA va aparte, por línea (RF-30).
    sale_price_cents: Mapped[int] = mapped_column(BigInteger)
    vat_bp: Mapped[int] = mapped_column(SmallInteger)
    # RF-38: lo copia la línea de presupuesto, y el presupuesto lo enseña.
    part_condition: Mapped[str] = mapped_column(String(20), server_default="new")
    # La garantía propia, si supera la de la reparación (RF-53).
    warranty_months: Mapped[int | None] = mapped_column(SmallInteger)
    # Un tornillo suelto no se cuenta; una batería sí (especificación §4).
    tracks_stock: Mapped[bool] = mapped_column(server_default="true")
    min_stock: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    archived_at: Mapped[datetime | None]
    # Para buscar por referencia, marca o descripción sin tildes ni mayúsculas,
    # con la misma función que la consulta (search_text, migración 0008search).
    search: Mapped[str] = mapped_column(
        Text,
        Computed(
            "search_text(reference || ' ' || coalesce(brand, '') || ' ' || description)",
            persisted=True,
        ),
    )
    version: Mapped[int] = mapped_column(server_default="1")

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012
