"""Documentos con valor de prueba (F6): la hoja de recepción firmada.

Una fila de `reception_sheets` es una hoja **firmada**: nace al firmarla, con la
copia congelada de los datos de recepción de ese momento, y no cambia nunca
(invariante 6, RNF-11). Mientras no está firmada no hay fila: la hoja se genera
desde los datos de la orden, que se siguen editando.

Lo congelado se reparte en dos sitios a propósito:

- `snapshot` guarda lo que no es un dato personal (el vehículo, los km, el
  combustible, los daños, los objetos, el motivo, la fecha prevista). El nombre
  del cliente no se congela: se lee al generar el PDF, como en el presupuesto,
  y desaparece al anonimizarlo (RF-15).
- Quien trajo el coche y quien firmó son columnas propias, porque son datos
  personales: al anonimizar al cliente se vacían, y es la única escritura que
  admite el trigger. La firma no se borra entonces: queda bloqueada hasta que
  vence su plazo (RF-56, F8).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.reception import SignatureMethod
from app.domain.work_orders import sql_in
from app.models.base import Base, CreatedAtMixin, IdMixin


class ReceptionSheet(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "reception_sheets"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        # Una hoja firmada por orden: firmar dos veces choca aquí (RF-52).
        UniqueConstraint("work_order_id"),
        ForeignKeyConstraint(
            ["work_order_id", "workshop_id"],
            ["work_orders.id", "work_orders.workshop_id"],
        ),
        ForeignKeyConstraint(
            ["recorded_by_employee_id", "workshop_id"],
            ["employees.id", "employees.workshop_id"],
        ),
        CheckConstraint(
            sql_in("signature_method", SignatureMethod), name="signature_method"
        ),
        # En papel no hay firma guardada; en pantalla la hay, salvo que ya se
        # haya borrado al vencer su plazo (RF-56).
        CheckConstraint(
            "(signature_method = 'paper'"
            " AND signature IS NULL AND signature_purged_at IS NULL)"
            " OR (signature_method = 'screen'"
            " AND (signature IS NULL) = (signature_purged_at IS NOT NULL))",
            name="signature_by_method",
        ),
        CheckConstraint("jsonb_typeof(snapshot) = 'object'", name="snapshot_object"),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    work_order_id: Mapped[UUID]
    # La hora la pone la base de datos (el trigger), como la de una decisión.
    signed_at: Mapped[datetime] = mapped_column(
        server_default=text("clock_timestamp()")
    )
    signature_method: Mapped[str] = mapped_column(String(10))
    # Quien marcó "firmada en papel" o recogió la firma en pantalla.
    recorded_by_employee_id: Mapped[UUID]
    # Los datos de recepción tal como se firmaron, sin datos personales.
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # La renuncia al presupuesto firmada: la que vale para RF-27.
    quote_waived: Mapped[bool]
    # Datos personales congelados: se vacían al anonimizar al cliente.
    dropped_off_by_name: Mapped[str | None] = mapped_column(String(200))
    dropped_off_by_phone: Mapped[str | None] = mapped_column(String(30))
    signer_name: Mapped[str | None] = mapped_column(String(200))
    # Los trazos de la firma en pantalla, reconstruidos por el servidor.
    # none_as_null: sin él, None se guarda como el JSON `null`, no como NULL, y
    # el CHECK de una firma en papel lo rechaza.
    signature: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # Cuándo se borró la firma al vencer su plazo (RF-56, F8).
    signature_purged_at: Mapped[datetime | None]
