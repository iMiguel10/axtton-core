"""Presupuestos (F3 paso 3, arquitectura §3): las tablas que hay que acertar a la
primera.

Una fila de `quotes` es **una versión**, no "el presupuesto": versionar es
insertar, y congelar es dejar de permitir cambios. Mientras es borrador se edita
libremente; al enviarla se guardan sus totales y desde entonces no cambia nada
salvo su estado (invariante 6, RNF-11). Lo garantizan, además del service, los
triggers de la migración 0013quotes, con cualquier rol.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.quotes import (
    DecisionChannel,
    DiscountKind,
    LineKind,
    Outcome,
    PartCondition,
    QuoteStatus,
)
from app.domain.work_orders import WorkOrderStatus, sql_in
from app.models.base import Base, CreatedAtMixin, IdMixin, UpdatedAtMixin

# Lo que se guarda al enviar y no existe en un borrador. Un CHECK exige que esté
# todo o nada, según el estado.
_SENT_FIELDS = (
    "sent_at",
    "sent_by_employee_id",
    "valid_until",
    "origin_status",
    "subtotal_cents",
    "global_discount_cents",
    "vat_breakdown",
    "total_cents",
)


class Quote(IdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        UniqueConstraint("work_order_id", "version_no"),
        ForeignKeyConstraint(
            ["work_order_id", "workshop_id"],
            ["work_orders.id", "work_orders.workshop_id"],
        ),
        ForeignKeyConstraint(
            ["created_by_employee_id", "workshop_id"],
            ["employees.id", "employees.workshop_id"],
        ),
        ForeignKeyConstraint(
            ["sent_by_employee_id", "workshop_id"],
            ["employees.id", "employees.workshop_id"],
        ),
        # La versión del diagnóstico que acompañó al envío tiene que ser de la
        # misma orden, no solo del mismo taller.
        ForeignKeyConstraint(
            ["diagnosis_version_id", "work_order_id", "workshop_id"],
            [
                "diagnosis_versions.id",
                "diagnosis_versions.work_order_id",
                "diagnosis_versions.workshop_id",
            ],
            # El nombre por convención pasaría de 63 caracteres y Postgres lo
            # cortaría en silencio.
            name="fk_quotes_diagnosis_version_same_order",
        ),
        CheckConstraint(sql_in("status", QuoteStatus), name="status"),
        CheckConstraint("version_no > 0", name="version_no"),
        CheckConstraint(
            f"origin_status IS NULL OR {sql_in('origin_status', WorkOrderStatus)}",
            name="origin_status",
        ),
        # Un borrador no tiene nada de lo que se guarda al enviar; una versión
        # enviada (en cualquier estado posterior) lo tiene todo.
        CheckConstraint(
            "(status = 'draft') = ("
            + " AND ".join(f"{field} IS NULL" for field in _SENT_FIELDS)
            + ") AND (status = 'draft' OR ("
            + " AND ".join(f"{field} IS NOT NULL" for field in _SENT_FIELDS)
            + "))",
            name="sent_fields",
        ),
        # El descuento global (RF-39): tipo y valor van juntos.
        CheckConstraint(
            f"(global_discount_kind IS NULL) = (global_discount_value IS NULL)"
            f" AND (global_discount_kind IS NULL OR"
            f" {sql_in('global_discount_kind', DiscountKind)})",
            name="global_discount",
        ),
        CheckConstraint(
            "global_discount_value IS NULL OR (global_discount_value >= 0 AND"
            " (global_discount_kind = 'amount' OR global_discount_value <= 10000))",
            name="global_discount_value",
        ),
        CheckConstraint(
            "subtotal_cents IS NULL OR (subtotal_cents >= 0 AND"
            " global_discount_cents BETWEEN 0 AND subtotal_cents AND total_cents >= 0)",
            name="totals",
        ),
        # Anular exige un motivo (especificación §6).
        CheckConstraint(
            "(status = 'cancelled') = (cancel_reason IS NOT NULL)",
            name="cancel_reason",
        ),
        # Como mucho una versión enviada por orden a la vez (arquitectura §3):
        # aunque el código fallara, dos `sent` no caben.
        Index(
            "uq_quotes_work_order_id_sent",
            "work_order_id",
            unique=True,
            postgresql_where=text("status = 'sent'"),
        ),
        # Y como mucho un borrador: corregir es crear la versión siguiente, y
        # dos borradores a la vez dejarían en el aire cuál se envía.
        Index(
            "uq_quotes_work_order_id_draft",
            "work_order_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    work_order_id: Mapped[UUID]
    version_no: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(20), server_default="draft")
    created_by_employee_id: Mapped[UUID]
    global_discount_kind: Mapped[str | None] = mapped_column(String(10))
    # Puntos básicos si es porcentaje; céntimos si es importe.
    global_discount_value: Mapped[int | None] = mapped_column(BigInteger)
    # --- Lo que se guarda al enviar (y no cambia nunca más) ---
    sent_at: Mapped[datetime | None]
    sent_by_employee_id: Mapped[UUID | None]
    # El instante en que deja de valer (RF-33): la medianoche que cierra el
    # último día hábil, en la zona del taller (domain/business_days.py).
    valid_until: Mapped[datetime | None]
    # Adonde vuelve la orden tras decidir o anular (especificación §6).
    origin_status: Mapped[str | None] = mapped_column(String(30))
    diagnosis_version_id: Mapped[UUID | None]
    subtotal_cents: Mapped[int | None] = mapped_column(BigInteger)
    global_discount_cents: Mapped[int | None] = mapped_column(BigInteger)
    # [{"vat_bp": 2100, "base_cents": …, "vat_cents": …}, …] (RF-30).
    vat_breakdown: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    total_cents: Mapped[int | None] = mapped_column(BigInteger)
    # --- Anulación ---
    cancel_reason: Mapped[str | None] = mapped_column(String(1000))
    version: Mapped[int] = mapped_column(server_default="1")

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class QuoteLine(IdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """Una línea de una versión. Su descripción, referencia y precio son una
    **copia** de la tarifa o del catálogo, nunca una referencia (RF-38): cambiar
    después la tarifa no cambia lo presupuestado."""

    __tablename__ = "quote_lines"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        UniqueConstraint("quote_id", "position"),
        ForeignKeyConstraint(
            ["quote_id", "workshop_id"], ["quotes.id", "quotes.workshop_id"]
        ),
        CheckConstraint(sql_in("kind", LineKind), name="kind"),
        CheckConstraint("position > 0", name="position"),
        # El estado de la pieza (RF-38) solo existe en las piezas, y toda pieza
        # lo tiene: "no lo sé" no es una respuesta que el cliente pueda aceptar.
        CheckConstraint(
            f"(kind = 'part') = (part_condition IS NOT NULL) AND"
            f" (part_condition IS NULL OR {sql_in('part_condition', PartCondition)})",
            name="part_condition",
        ),
        CheckConstraint("quantity > 0", name="quantity"),
        CheckConstraint("unit_price_cents >= 0", name="unit_price_cents"),
        CheckConstraint("discount_bp BETWEEN 0 AND 10000", name="discount_bp"),
        CheckConstraint("vat_bp BETWEEN 0 AND 10000", name="vat_bp"),
        # Los importes de la línea se escriben al enviar, todos a la vez.
        CheckConstraint(
            "(gross_cents IS NULL) = (line_total_cents IS NULL)"
            " AND (gross_cents IS NULL) = (discount_cents IS NULL)"
            " AND (gross_cents IS NULL) = (global_discount_share_cents IS NULL)"
            " AND (gross_cents IS NULL) = (taxable_cents IS NULL)"
            " AND (gross_cents IS NULL) = (vat_cents IS NULL)",
            name="amounts_together",
        ),
        CheckConstraint(
            "line_total_cents IS NULL OR (taxable_cents >= 0 AND"
            " gross_cents - discount_cents - global_discount_share_cents"
            " = taxable_cents AND taxable_cents + vat_cents = line_total_cents)",
            name="amounts_add_up",
        ),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    quote_id: Mapped[UUID]
    position: Mapped[int] = mapped_column(SmallInteger)
    kind: Mapped[str] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(String(500))
    reference: Mapped[str | None] = mapped_column(String(100))
    part_condition: Mapped[str | None] = mapped_column(String(20))
    # Litros de aceite: tres decimales (convenciones §3).
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    unit_price_cents: Mapped[int] = mapped_column(BigInteger)
    discount_bp: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    vat_bp: Mapped[int] = mapped_column(SmallInteger)
    # Costura para la aprobación por líneas, sin usar (arquitectura §3).
    optional: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # --- Lo que calcula domain/quotes.py al enviar (RNF-14) ---
    gross_cents: Mapped[int | None] = mapped_column(BigInteger)
    discount_cents: Mapped[int | None] = mapped_column(BigInteger)
    global_discount_share_cents: Mapped[int | None] = mapped_column(BigInteger)
    taxable_cents: Mapped[int | None] = mapped_column(BigInteger)
    vat_cents: Mapped[int | None] = mapped_column(BigInteger)
    line_total_cents: Mapped[int | None] = mapped_column(BigInteger)


class QuoteDecision(IdMixin, CreatedAtMixin, Base):
    """La aprobación o el rechazo de una versión enviada (RF-34 a RF-36).
    Append-only: ni la aplicación ni la plataforma pueden cambiarla o borrarla."""

    __tablename__ = "quote_decisions"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        # Una decisión por versión: dos pestañas que deciden a la vez, la
        # segunda choca (arquitectura §7.1).
        UniqueConstraint("quote_id"),
        ForeignKeyConstraint(
            ["quote_id", "workshop_id"], ["quotes.id", "quotes.workshop_id"]
        ),
        ForeignKeyConstraint(
            ["recorded_by_employee_id", "workshop_id"],
            ["employees.id", "employees.workshop_id"],
            name="fk_quote_decisions_recorded_by_employees",
        ),
        CheckConstraint(sql_in("outcome", Outcome), name="outcome"),
        CheckConstraint(sql_in("channel", DecisionChannel), name="channel"),
        # En el portal decide el cliente y quedan su IP y su navegador; por
        # teléfono o en persona, la registra un empleado (RF-35, RF-36).
        CheckConstraint(
            "(channel = 'portal') = (recorded_by_employee_id IS NULL)",
            name="recorded_by",
        ),
        CheckConstraint(
            "channel = 'portal' OR (ip IS NULL AND user_agent IS NULL)",
            name="portal_only_fields",
        ),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    quote_id: Mapped[UUID]
    outcome: Mapped[str] = mapped_column(String(10))
    channel: Mapped[str] = mapped_column(String(10))
    recorded_by_employee_id: Mapped[UUID | None]
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(500))
    note: Mapped[str | None] = mapped_column(String(2000))
    decided_at: Mapped[datetime] = mapped_column(
        server_default=text("clock_timestamp()")
    )
