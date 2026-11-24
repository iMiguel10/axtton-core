"""Catálogo de piezas (F7 paso 1, RF-90)

`parts`: lo que el taller vende o monta, con su referencia (única en el taller,
sin distinguir mayúsculas, también archivada), su descripción y marca, el precio
de coste y el de venta, el IVA, su estado (RF-38), la garantía propia si supera
la de la reparación (RF-53), si se cuenta su stock y el mínimo (RF-95). El stock
no es una columna: llegará como la suma de `stock_movements` (paso 2,
invariante 9).

Generada con --autogenerate y revisada a mano. Lo añadido a mano:

- RLS forzada con la política del taller.
- Una pieza no se borra, se archiva: `axtton_app` no tiene `DELETE`, y de
  `UPDATE` solo lo que edita el administrador (no el taller ni el id).
- `workshops.max_parts`, el límite del plan (§10), con su CHECK, que
  --autogenerate no detecta.

La política se repite aquí en lugar de importar el ayudante de 0001f1base: una
migración ya aplicada no debe cambiar si mañana cambia una función compartida.

Revision ID: 0027parts
Revises: 0026frozenjson
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027parts"
down_revision: str | None = "0026frozenjson"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Lo que `axtton_app` puede cambiar de una pieza: lo que edita el administrador,
# archivarla y el bloqueo optimista.
PART_UPDATABLE = (
    "reference",
    "description",
    "brand",
    "cost_price_cents",
    "sale_price_cents",
    "vat_bp",
    "part_condition",
    "warranty_months",
    "tracks_stock",
    "min_stock",
    "archived_at",
    "version",
    "updated_at",
)


def upgrade() -> None:
    op.create_table(
        "parts",
        sa.Column("workshop_id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("brand", sa.String(length=100), nullable=True),
        sa.Column("cost_price_cents", sa.BigInteger(), nullable=True),
        sa.Column("sale_price_cents", sa.BigInteger(), nullable=False),
        sa.Column("vat_bp", sa.SmallInteger(), nullable=False),
        sa.Column(
            "part_condition", sa.String(length=20), server_default="new", nullable=False
        ),
        sa.Column("warranty_months", sa.SmallInteger(), nullable=True),
        sa.Column("tracks_stock", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("min_stock", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "search",
            sa.Text(),
            sa.Computed(
                "search_text(reference || ' ' || coalesce(brand, '') || ' ' || description)",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "part_condition IN ('new', 'used', 'reconditioned', 'non_specific')",
            name=op.f("ck_parts_part_condition"),
        ),
        sa.CheckConstraint(
            "cost_price_cents >= 0", name=op.f("ck_parts_cost_price_cents")
        ),
        sa.CheckConstraint(
            "length(btrim(description)) > 0", name=op.f("ck_parts_description")
        ),
        sa.CheckConstraint(
            "length(btrim(reference)) > 0", name=op.f("ck_parts_reference")
        ),
        sa.CheckConstraint(
            "min_stock IS NULL OR (tracks_stock AND min_stock >= 0)",
            name=op.f("ck_parts_min_stock"),
        ),
        sa.CheckConstraint(
            "sale_price_cents >= 0", name=op.f("ck_parts_sale_price_cents")
        ),
        sa.CheckConstraint("vat_bp BETWEEN 0 AND 10000", name=op.f("ck_parts_vat_bp")),
        sa.CheckConstraint(
            "warranty_months BETWEEN 4 AND 120", name=op.f("ck_parts_warranty_months")
        ),
        sa.ForeignKeyConstraint(
            ["workshop_id"],
            ["workshops.id"],
            name=op.f("fk_parts_workshop_id_workshops"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parts")),
        sa.UniqueConstraint("id", "workshop_id", name=op.f("uq_parts_id_workshop_id")),
    )
    op.create_index(
        "uq_parts_workshop_id_reference",
        "parts",
        ["workshop_id", sa.literal_column("lower(reference)")],
        unique=True,
    )
    op.add_column(
        "workshops",
        sa.Column("max_parts", sa.Integer(), server_default="10000", nullable=False),
    )

    # --- A mano: lo que --autogenerate no sabe hacer ---

    op.create_check_constraint(
        op.f("ck_workshops_max_parts"), "workshops", "max_parts > 0"
    )
    op.execute("ALTER TABLE parts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE parts FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY workshop_isolation ON parts
            USING (workshop_id = ANY (app_current_workshops()))
            WITH CHECK (workshop_id = ANY (app_current_workshops()))
        """
    )
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON parts FROM axtton_app")
    op.execute(f"GRANT UPDATE ({', '.join(PART_UPDATABLE)}) ON parts TO axtton_app")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_workshops_max_parts"), "workshops")
    op.drop_column("workshops", "max_parts")
    op.drop_index("uq_parts_workshop_id_reference", table_name="parts")
    op.drop_table("parts")
