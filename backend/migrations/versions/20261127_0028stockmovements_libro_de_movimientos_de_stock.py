"""Libro de movimientos de stock (F7 paso 2, RF-91 a RF-96, RNF-12, RNF-13)

`stock_movements`: cada fila es un apunte con su cantidad con signo (entra,
sale, ajuste o anulación) y quién lo anotó, ordenado por `seq`. El stock de una
pieza no es una columna: es la suma de sus movimientos (invariante 9).

Generada con --autogenerate y revisada a mano. Lo añadido a mano:

- RLS forzada con la política del taller.
- **Append-only con cualquier rol** (RNF-12): ni `axtton_app` ni
  `axtton_platform` tienen `UPDATE`, `DELETE` ni `TRUNCATE`, y el trigger
  `stock_movements_frozen` rechaza `UPDATE` y `DELETE` también al dueño de las
  tablas (como `quote_decisions_frozen`, 0015decisionsfrozen). `TRUNCATE` no
  dispara triggers de fila: `reset_data.py` y la demo siguen pudiendo vaciar.
- `stock_movements_reversal_matches`: una anulación es exactamente la
  contraria de su original (misma pieza, cantidad opuesta) y no se anula otra
  anulación. Que se anule una sola vez lo dice el índice único de
  `reverses_id`.

La política se repite aquí en lugar de importar el ayudante de 0001f1base: una
migración ya aplicada no debe cambiar si mañana cambia una función compartida.

Revision ID: 0028stockmovements
Revises: 0027parts
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028stockmovements"
down_revision: str | None = "0027parts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_movements",
        sa.Column("workshop_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("part_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("unit_cost_cents", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("counted_stock", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("reverses_id", sa.Uuid(), nullable=True),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'in') = (unit_cost_cents IS NOT NULL) AND unit_cost_cents >= 0",
            name=op.f("ck_stock_movements_unit_cost_cents"),
        ),
        sa.CheckConstraint(
            "(kind = 'reversal') = (reverses_id IS NOT NULL)",
            name=op.f("ck_stock_movements_reverses"),
        ),
        sa.CheckConstraint(
            "counted_stock IS NULL OR kind = 'adjustment'",
            name=op.f("ck_stock_movements_counted_stock"),
        ),
        sa.CheckConstraint(
            "kind IN ('in', 'out', 'adjustment', 'reversal')",
            name=op.f("ck_stock_movements_kind"),
        ),
        sa.CheckConstraint(
            "kind NOT IN ('adjustment', 'reversal') OR coalesce(length(btrim(note)), 0) > 0"
            " OR (kind = 'adjustment' AND counted_stock IS NOT NULL)",
            name=op.f("ck_stock_movements_note"),
        ),
        sa.CheckConstraint(
            "quantity <> 0 AND (kind <> 'in' OR quantity > 0)"
            " AND (kind <> 'out' OR quantity < 0)",
            name=op.f("ck_stock_movements_quantity"),
        ),
        sa.ForeignKeyConstraint(
            ["employee_id", "workshop_id"],
            ["employees.id", "employees.workshop_id"],
            name=op.f("fk_stock_movements_employee_id_workshop_id_employees"),
        ),
        sa.ForeignKeyConstraint(
            ["part_id", "workshop_id"],
            ["parts.id", "parts.workshop_id"],
            name=op.f("fk_stock_movements_part_id_workshop_id_parts"),
        ),
        sa.ForeignKeyConstraint(
            ["reverses_id", "workshop_id"],
            ["stock_movements.id", "stock_movements.workshop_id"],
            name=op.f("fk_stock_movements_reverses_id_workshop_id_stock_movements"),
        ),
        sa.ForeignKeyConstraint(
            ["workshop_id"],
            ["workshops.id"],
            name=op.f("fk_stock_movements_workshop_id_workshops"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_movements")),
        sa.UniqueConstraint(
            "id", "workshop_id", name=op.f("uq_stock_movements_id_workshop_id")
        ),
        sa.UniqueConstraint("seq", name=op.f("uq_stock_movements_seq")),
    )
    op.create_index(
        "ix_stock_movements_workshop_id_part_id",
        "stock_movements",
        ["workshop_id", "part_id"],
        unique=False,
        postgresql_include=["quantity"],
    )
    op.create_index(
        "uq_stock_movements_reverses_id",
        "stock_movements",
        ["reverses_id"],
        unique=True,
    )

    # --- A mano: lo que --autogenerate no sabe hacer ---

    op.execute("ALTER TABLE stock_movements ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE stock_movements FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY workshop_isolation ON stock_movements
            USING (workshop_id = ANY (app_current_workshops()))
            WITH CHECK (workshop_id = ANY (app_current_workshops()))
        """
    )
    # RNF-12 lo garantiza la base de datos, no la disciplina del código.
    op.execute(
        "REVOKE UPDATE, DELETE, TRUNCATE ON stock_movements"
        " FROM axtton_app, axtton_platform"
    )

    op.execute(
        """
        CREATE FUNCTION stock_movements_frozen() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'stock movement % cannot change: it is a ledger', OLD.id
                USING ERRCODE = 'check_violation';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER stock_movements_frozen
            BEFORE UPDATE OR DELETE ON stock_movements
            FOR EACH ROW EXECUTE FUNCTION stock_movements_frozen()
        """
    )

    # La anulación, contrastada con su original. Bajo RLS, el original de otro
    # taller no se ve: se para aquí con "not found", antes que la FK compuesta.
    op.execute(
        """
        CREATE FUNCTION stock_movements_reversal_matches() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            original stock_movements%ROWTYPE;
        BEGIN
            IF NEW.kind <> 'reversal' THEN
                RETURN NEW;
            END IF;
            SELECT * INTO original FROM stock_movements WHERE id = NEW.reverses_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'stock movement % not found', NEW.reverses_id
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF original.kind = 'reversal' THEN
                RAISE EXCEPTION 'a reversal cannot be reversed'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF original.part_id <> NEW.part_id
                    OR original.quantity <> -NEW.quantity THEN
                RAISE EXCEPTION 'a reversal must undo exactly its movement'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER stock_movements_reversal_matches
            BEFORE INSERT ON stock_movements
            FOR EACH ROW EXECUTE FUNCTION stock_movements_reversal_matches()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER stock_movements_reversal_matches ON stock_movements")
    op.execute("DROP FUNCTION stock_movements_reversal_matches()")
    op.execute("DROP TRIGGER stock_movements_frozen ON stock_movements")
    op.execute("DROP FUNCTION stock_movements_frozen()")
    op.drop_index("uq_stock_movements_reverses_id", table_name="stock_movements")
    op.drop_index(
        "ix_stock_movements_workshop_id_part_id",
        table_name="stock_movements",
        postgresql_include=["quantity"],
    )
    op.drop_table("stock_movements")
