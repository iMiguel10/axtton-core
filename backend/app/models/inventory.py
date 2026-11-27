"""El inventario del taller (F7, arquitectura §3): el catálogo de piezas y el
libro de movimientos de stock.

Sigue la regla del multi-taller, con RLS forzada en las migraciones 0027parts y
0028stockmovements. Una pieza no se borra (tiene movimientos y órdenes que la
montaron): se archiva, y deja de salir al elegir. Un movimiento no se cambia ni
se borra jamás (RNF-12): el stock es su suma (invariante 9).
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.inventory import (
    PART_WARRANTY_MAX_MONTHS,
    PART_WARRANTY_MIN_MONTHS,
    MovementKind,
)
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


class StockMovement(IdMixin, CreatedAtMixin, Base):
    """Un apunte del libro de stock (RF-91 a RF-94, RNF-12, RNF-13).

    Append-only con cualquier rol: `axtton_app` solo tiene SELECT e INSERT, y el
    trigger `stock_movements_frozen` rechaza UPDATE y DELETE también al dueño.
    Como solo se insertan filas, dos salidas a la vez nunca se pisan: el stock
    se calcula, no se lee, se resta y se escribe (RNF-13).
    """

    __tablename__ = "stock_movements"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        ForeignKeyConstraint(
            ["part_id", "workshop_id"], ["parts.id", "parts.workshop_id"]
        ),
        ForeignKeyConstraint(
            ["employee_id", "workshop_id"],
            ["employees.id", "employees.workshop_id"],
        ),
        ForeignKeyConstraint(
            ["reverses_id", "workshop_id"],
            ["stock_movements.id", "stock_movements.workshop_id"],
        ),
        CheckConstraint(sql_in("kind", MovementKind), name="kind"),
        # El signo va con el tipo: entra lo que llega, sale lo que se monta.
        CheckConstraint(
            "quantity <> 0"
            " AND (kind <> 'in' OR quantity > 0)"
            " AND (kind <> 'out' OR quantity < 0)",
            name="quantity",
        ),
        # El coste por unidad es de las entradas, y toda entrada lo tiene (RF-91).
        CheckConstraint(
            "(kind = 'in') = (unit_cost_cents IS NOT NULL) AND unit_cost_cents >= 0",
            name="unit_cost_cents",
        ),
        # Un ajuste lleva su motivo (RF-92) o es un recuento; una anulación,
        # siempre su motivo. Con `coalesce`: sin él, una nota nula da NULL, y un
        # CHECK que da NULL se cumple (lo vio test_stock_db.py).
        CheckConstraint(
            "kind NOT IN ('adjustment', 'reversal')"
            " OR coalesce(length(btrim(note)), 0) > 0"
            " OR (kind = 'adjustment' AND counted_stock IS NOT NULL)",
            name="note",
        ),
        CheckConstraint(
            "counted_stock IS NULL OR kind = 'adjustment'", name="counted_stock"
        ),
        CheckConstraint(
            "(kind = 'reversal') = (reverses_id IS NOT NULL)", name="reverses"
        ),
        # Un movimiento se anula una sola vez: dos anulaciones a la vez chocan
        # aquí (la comprobación previa no las ve).
        Index("uq_stock_movements_reverses_id", "reverses_id", unique=True),
        # El stock de una pieza es la suma de sus movimientos: este índice la
        # sirve sin tocar la tabla (cantidad incluida).
        Index(
            "ix_stock_movements_workshop_id_part_id",
            "workshop_id",
            "part_id",
            postgresql_include=["quantity"],
        ),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    # El orden del libro (arquitectura §3): nunca la fecha.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    part_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    unit_cost_cents: Mapped[int | None] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(String(500))
    # En un ajuste por recuento, lo que se contó (RF-92): el ajuste es la
    # diferencia con el stock que había.
    counted_stock: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    reverses_id: Mapped[UUID | None]
    # Quién lo anotó.
    employee_id: Mapped[UUID]
