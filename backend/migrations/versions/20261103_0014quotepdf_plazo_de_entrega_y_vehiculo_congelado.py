"""Plazo de entrega y vehículo congelado al enviar (F3 paso 7, RF-37, RF-55)

El PDF del presupuesto tiene que llevar la fecha prevista de entrega "a contar
desde la aceptación" y el vehículo con sus kilómetros. Dos columnas en `quotes`:

- `delivery_business_days`: el plazo, en días hábiles desde la aceptación. Se
  escribe en el borrador y sin él no se envía (CHECK). La fecha sale al decidir.
- `vehicle_snapshot`: la matrícula, la marca, el modelo y los km tal como eran
  al enviar. Entra en `ck_quotes_sent_fields`: un borrador no lo tiene y una
  versión enviada sí. Corregir después la ficha del vehículo o la recepción no
  cambia lo que se presupuestó.

El trigger `quotes_frozen_after_send` compara la fila entera en jsonb, así que
las dos columnas quedan congeladas al enviar sin tocarlo.

Y una en `workshops`, `default_delivery_business_days`: el plazo con el que
empieza cada presupuesto nuevo, que edita el administrador del taller (RF-02).
Puede quedar vacía. `axtton_app` recibe `UPDATE` sobre ella, como sobre los
demás ajustes (0012settings).

Las versiones ya enviadas se rellenan aquí: el vehículo, con lo que hay ahora en
su ficha y en su orden (no hay nada mejor), y el plazo, con 5 días. Solo existen
en la demo, que se recarga cada noche, y en las bases de desarrollo. Para
escribirlas, el dueño quita dentro de esta transacción la RLS forzada (si no,
sin taller fijado no vería ninguna fila) y el trigger que congela lo enviado, y
los vuelve a poner antes de terminar.

Revision ID: 0014quotepdf
Revises: 0013quotes
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014quotepdf"
down_revision: str | None = "0013quotes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_COLUMNS = ("delivery_business_days", "vehicle_snapshot")

# Lo que se guarda al enviar, como en app/models/quotes.py: aquí escrito a mano,
# para que esta migración no cambie si mañana cambia el modelo.
SENT_FIELDS_BEFORE = (
    "sent_at",
    "sent_by_employee_id",
    "valid_until",
    "origin_status",
    "subtotal_cents",
    "global_discount_cents",
    "vat_breakdown",
    "total_cents",
)
SENT_FIELDS_AFTER = (*SENT_FIELDS_BEFORE, "vehicle_snapshot")

BACKFILL_TABLES = ("quotes", "work_orders", "vehicles")


def _sent_fields(fields: tuple[str, ...]) -> str:
    return (
        "(status = 'draft') = ("
        + " AND ".join(f"{field} IS NULL" for field in fields)
        + ") AND (status = 'draft' OR ("
        + " AND ".join(f"{field} IS NOT NULL" for field in fields)
        + "))"
    )


def upgrade() -> None:
    op.add_column(
        "quotes", sa.Column("delivery_business_days", sa.SmallInteger(), nullable=True)
    )
    op.add_column(
        "quotes",
        sa.Column(
            "vehicle_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    # Las versiones ya enviadas, antes de los CHECK que las exigen.
    for table in BACKFILL_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE quotes DISABLE TRIGGER quotes_frozen_after_send")
    op.execute(
        """
        UPDATE quotes q
           SET delivery_business_days = 5,
               vehicle_snapshot = jsonb_build_object(
                   'plate', v.plate,
                   'make', v.make,
                   'model', v.model,
                   'odometer_km', o.odometer_km)
          FROM work_orders o
          JOIN vehicles v ON v.id = o.vehicle_id
         WHERE o.id = q.work_order_id AND q.status <> 'draft'
        """
    )
    op.execute("ALTER TABLE quotes ENABLE TRIGGER quotes_frozen_after_send")
    for table in BACKFILL_TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.create_check_constraint(
        "delivery_business_days",
        "quotes",
        "(delivery_business_days IS NULL OR delivery_business_days BETWEEN 1 AND 250)"
        " AND (status = 'draft' OR delivery_business_days IS NOT NULL)",
    )
    op.drop_constraint("sent_fields", "quotes", type_="check")
    op.create_check_constraint("sent_fields", "quotes", _sent_fields(SENT_FIELDS_AFTER))

    # El plazo se edita en el borrador y el vehículo se escribe al enviar.
    op.execute(f"GRANT UPDATE ({', '.join(NEW_COLUMNS)}) ON quotes TO axtton_app")

    op.add_column(
        "workshops",
        sa.Column("default_delivery_business_days", sa.SmallInteger(), nullable=True),
    )
    op.create_check_constraint(
        "default_delivery_business_days",
        "workshops",
        "default_delivery_business_days IS NULL"
        " OR default_delivery_business_days BETWEEN 1 AND 250",
    )
    op.execute(
        "GRANT UPDATE (default_delivery_business_days) ON workshops TO axtton_app"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE UPDATE (default_delivery_business_days) ON workshops FROM axtton_app"
    )
    op.drop_column("workshops", "default_delivery_business_days")
    op.execute(f"REVOKE UPDATE ({', '.join(NEW_COLUMNS)}) ON quotes FROM axtton_app")
    op.drop_constraint("sent_fields", "quotes", type_="check")
    op.create_check_constraint(
        "sent_fields", "quotes", _sent_fields(SENT_FIELDS_BEFORE)
    )
    op.drop_constraint("delivery_business_days", "quotes", type_="check")
    op.drop_column("quotes", "vehicle_snapshot")
    op.drop_column("quotes", "delivery_business_days")
