"""Cobro de las órdenes y anonimización de clientes (F2 paso 8, RF-28, RF-29, RF-15)

**El cobro** son cuatro columnas de `work_orders`, no un estado (§6): cobrada,
pendiente o sin cargo; y, si está cobrada, forma de pago, importe y fecha. Dos
CHECK lo mantienen coherente: solo una orden cerrada deja de estar pendiente, y
los detalles van si y solo si está cobrada. Un índice parcial sirve el listado
de entregadas pendientes de cobro (RF-29).

**Anonimizar** vacía los datos personales del cliente y conserva su fila, para
que sus órdenes sigan apuntando a algo (arquitectura §3). Lo garantiza la base
de datos con dos piezas:

- un CHECK: con `anonymized_at`, el nombre y el teléfono están vacíos, lo
  opcional es nulo y el cliente está archivado;
- un trigger, `clients_anonymized_frozen`: un cliente anonimizado no se vuelve
  a tocar, con ningún rol. Sin él, bastaría un UPDATE para "desanonimizar" la
  fila con otros datos, y RF-15 dice que es irreversible.

Alembic no detecta los CHECK al generar: están escritos a mano.

Revision ID: 0009payment
Revises: 0008search
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009payment"
down_revision: str | None = "0008search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_clients_anonymized_empty"),
        "clients",
        "anonymized_at IS NULL OR (name = '' AND phone = '' AND email IS NULL"
        " AND tax_id IS NULL AND address IS NULL AND notes IS NULL"
        " AND archived_at IS NOT NULL)",
    )
    op.execute(
        """
        CREATE FUNCTION clients_anonymized_frozen() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.anonymized_at IS NOT NULL THEN
                RAISE EXCEPTION 'an anonymized client cannot be changed'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER clients_anonymized_frozen
            BEFORE UPDATE ON clients
            FOR EACH ROW EXECUTE FUNCTION clients_anonymized_frozen()
        """
    )

    op.add_column(
        "work_orders",
        sa.Column(
            "payment_status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "work_orders", sa.Column("payment_method", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "work_orders", sa.Column("paid_amount_cents", sa.BigInteger(), nullable=True)
    )
    op.add_column("work_orders", sa.Column("paid_on", sa.Date(), nullable=True))
    op.create_check_constraint(
        op.f("ck_work_orders_payment_status"),
        "work_orders",
        "payment_status IN ('pending', 'paid', 'no_charge')",
    )
    op.create_check_constraint(
        op.f("ck_work_orders_payment_method"),
        "work_orders",
        "payment_method IN ('cash', 'card', 'transfer', 'other')",
    )
    op.create_check_constraint(
        op.f("ck_work_orders_paid_amount_cents"),
        "work_orders",
        "paid_amount_cents > 0",
    )
    op.create_check_constraint(
        op.f("ck_work_orders_payment_when_closed"),
        "work_orders",
        "payment_status = 'pending' OR status IN ('delivered', 'cancelled')",
    )
    op.create_check_constraint(
        op.f("ck_work_orders_payment_details"),
        "work_orders",
        "(payment_status = 'paid') = (payment_method IS NOT NULL)"
        " AND (payment_status = 'paid') = (paid_amount_cents IS NOT NULL)"
        " AND (payment_status = 'paid') = (paid_on IS NOT NULL)",
    )
    op.create_index(
        "ix_work_orders_unpaid",
        "work_orders",
        ["workshop_id", "delivered_at"],
        unique=False,
        postgresql_where=sa.text("status = 'delivered' AND payment_status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_work_orders_unpaid", table_name="work_orders")
    for name in (
        "payment_details",
        "payment_when_closed",
        "paid_amount_cents",
        "payment_method",
        "payment_status",
    ):
        op.drop_constraint(op.f(f"ck_work_orders_{name}"), "work_orders")
    op.drop_column("work_orders", "paid_on")
    op.drop_column("work_orders", "paid_amount_cents")
    op.drop_column("work_orders", "payment_method")
    op.drop_column("work_orders", "payment_status")
    op.execute("DROP TRIGGER clients_anonymized_frozen ON clients")
    op.execute("DROP FUNCTION clients_anonymized_frozen()")
    op.drop_constraint(op.f("ck_clients_anonymized_empty"), "clients")
    op.drop_column("clients", "anonymized_at")
