"""La hoja de recepción firmada (F6 paso 1, RF-51, RF-52, invariante 6)

Los datos de recepción siguen en la orden, y se completan con lo que pide el
resguardo de depósito (RF-51): el nivel de combustible, los daños visibles y los
objetos por separado (`reception_notes` pasa a ser `visible_damage`, con lo que
tenía) y la renuncia expresa al presupuesto.

`reception_sheets` guarda la hoja **firmada**, una por orden: nace al firmarla con
la copia congelada de esos datos y no cambia nunca, con cualquier rol, como un
presupuesto enviado. El trigger admite una sola escritura: vaciar quién trajo el
coche y quién firmó cuando su cliente ya está anonimizado (RF-15, RNF-40). La
firma no se vacía entonces: queda bloqueada hasta que vence su plazo (RF-56), que
llega con F8 y con su propia excepción. Nadie borra una hoja.

Revision ID: 0024receptionsheets
Revises: 0023noticefinal
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024receptionsheets"
down_revision: str | None = "0023noticefinal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUEL_LEVELS = "'reserve', 'quarter', 'half', 'three_quarters', 'full'"
# Los datos de recepción nuevos de la orden, que el taller edita (0011ordercols).
ORDER_UPDATABLE = ("visible_damage", "belongings", "fuel_level", "quote_waived")
# Lo único que la aplicación puede escribir de una hoja firmada (al anonimizar).
SHEET_ERASABLE = ("dropped_off_by_name", "dropped_off_by_phone", "signer_name")


def upgrade() -> None:
    # --- Los datos de recepción de la orden (RF-51) ------------------------------
    # Renombrada, no borrada: lo anotado hasta hoy eran sobre todo los daños.
    # El permiso por columna de 0011ordercols sigue con ella.
    op.alter_column("work_orders", "reception_notes", new_column_name="visible_damage")
    op.add_column(
        "work_orders", sa.Column("belongings", sa.String(length=2000), nullable=True)
    )
    op.add_column(
        "work_orders", sa.Column("fuel_level", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "work_orders",
        sa.Column("quote_waived", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_check_constraint(
        "fuel_level", "work_orders", f"fuel_level IN ({FUEL_LEVELS})"
    )
    op.execute(
        f"GRANT UPDATE ({', '.join(ORDER_UPDATABLE)}) ON work_orders TO axtton_app"
    )

    # --- La hoja firmada ---------------------------------------------------------
    op.create_table(
        "reception_sheets",
        sa.Column("workshop_id", sa.Uuid(), nullable=False),
        sa.Column("work_order_id", sa.Uuid(), nullable=False),
        sa.Column(
            "signed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("signature_method", sa.String(length=10), nullable=False),
        sa.Column("recorded_by_employee_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quote_waived", sa.Boolean(), nullable=False),
        sa.Column("dropped_off_by_name", sa.String(length=200), nullable=True),
        sa.Column("dropped_off_by_phone", sa.String(length=30), nullable=True),
        sa.Column("signer_name", sa.String(length=200), nullable=True),
        sa.Column("signature", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("signature_purged_at", sa.DateTime(timezone=True), nullable=True),
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
            "(signature_method = 'paper'"
            " AND signature IS NULL AND signature_purged_at IS NULL)"
            " OR (signature_method = 'screen'"
            " AND (signature IS NULL) = (signature_purged_at IS NOT NULL))",
            name=op.f("ck_reception_sheets_signature_by_method"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(snapshot) = 'object'",
            name=op.f("ck_reception_sheets_snapshot_object"),
        ),
        sa.CheckConstraint(
            "signature_method IN ('screen', 'paper')",
            name=op.f("ck_reception_sheets_signature_method"),
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_employee_id", "workshop_id"],
            ["employees.id", "employees.workshop_id"],
            name=op.f(
                "fk_reception_sheets_recorded_by_employee_id_workshop_id_employees"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["work_order_id", "workshop_id"],
            ["work_orders.id", "work_orders.workshop_id"],
            name=op.f("fk_reception_sheets_work_order_id_workshop_id_work_orders"),
        ),
        sa.ForeignKeyConstraint(
            ["workshop_id"],
            ["workshops.id"],
            name=op.f("fk_reception_sheets_workshop_id_workshops"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reception_sheets")),
        sa.UniqueConstraint(
            "id", "workshop_id", name=op.f("uq_reception_sheets_id_workshop_id")
        ),
        sa.UniqueConstraint(
            "work_order_id", name=op.f("uq_reception_sheets_work_order_id")
        ),
    )

    # Congelada al nacer (invariante 6), con cualquier rol: el dueño y la
    # plataforma también pasan por aquí. Con IF separados: un DELETE no tiene NEW,
    # y PL/pgSQL resuelve toda la expresión (trampa de CLAUDE.md).
    op.execute(
        """
        CREATE FUNCTION reception_sheets_frozen() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                -- La hora de la firma es la del servidor, no la que mande nadie.
                NEW.signed_at := clock_timestamp();
                IF NEW.signature_purged_at IS NOT NULL THEN
                    RAISE EXCEPTION 'a reception sheet is not signed already purged'
                        USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'UPDATE' THEN
                -- La única escritura: vaciar lo personal de una hoja cuyo
                -- cliente ya está anonimizado (RF-15, RNF-40). La firma se queda
                -- hasta su plazo (RF-56).
                IF NEW.dropped_off_by_name IS NULL
                    AND NEW.dropped_off_by_phone IS NULL
                    AND NEW.signer_name IS NULL
                    AND (NEW.id, NEW.workshop_id, NEW.work_order_id, NEW.signed_at,
                         NEW.signature_method, NEW.recorded_by_employee_id,
                         NEW.snapshot, NEW.quote_waived, NEW.signature,
                         NEW.signature_purged_at, NEW.created_at)
                        IS NOT DISTINCT FROM
                        (OLD.id, OLD.workshop_id, OLD.work_order_id, OLD.signed_at,
                         OLD.signature_method, OLD.recorded_by_employee_id,
                         OLD.snapshot, OLD.quote_waived, OLD.signature,
                         OLD.signature_purged_at, OLD.created_at)
                    AND EXISTS (
                        SELECT 1
                        FROM work_orders o
                        JOIN clients c ON c.id = o.client_id
                        WHERE o.id = OLD.work_order_id AND c.anonymized_at IS NOT NULL
                    )
                THEN
                    RETURN NEW;
                END IF;
            END IF;
            RAISE EXCEPTION 'the reception sheet of order % was signed: it cannot change',
                OLD.work_order_id
                USING ERRCODE = 'check_violation';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER reception_sheets_frozen
            BEFORE INSERT OR UPDATE OR DELETE ON reception_sheets
            FOR EACH ROW EXECUTE FUNCTION reception_sheets_frozen()
        """
    )

    # RLS forzada con la política común (arquitectura §4).
    op.execute("ALTER TABLE reception_sheets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reception_sheets FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY workshop_isolation ON reception_sheets
            USING (workshop_id = ANY (app_current_workshops()))
            WITH CHECK (workshop_id = ANY (app_current_workshops()))
        """
    )
    op.execute("REVOKE UPDATE, DELETE ON reception_sheets FROM axtton_app")
    op.execute(
        f"GRANT UPDATE ({', '.join(SHEET_ERASABLE)}) ON reception_sheets TO axtton_app"
    )


def downgrade() -> None:
    op.drop_table("reception_sheets")
    op.execute("DROP FUNCTION reception_sheets_frozen()")
    op.execute(
        f"REVOKE UPDATE ({', '.join(ORDER_UPDATABLE)}) ON work_orders FROM axtton_app"
    )
    op.drop_constraint("fuel_level", "work_orders", type_="check")
    # Los objetos vuelven a la columna de la que salieron, para no perderlos. Sin
    # quitar FORCE, el dueño tampoco vería ninguna orden (RLS forzada).
    op.execute("ALTER TABLE work_orders NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE work_orders SET visible_damage = left(concat_ws(E'\\n',"
        " visible_damage, belongings), 2000) WHERE belongings IS NOT NULL"
    )
    op.execute("ALTER TABLE work_orders FORCE ROW LEVEL SECURITY")
    op.drop_column("work_orders", "quote_waived")
    op.drop_column("work_orders", "fuel_level")
    op.drop_column("work_orders", "belongings")
    op.alter_column("work_orders", "visible_damage", new_column_name="reception_notes")
