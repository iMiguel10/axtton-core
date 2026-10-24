"""F0: presupuestos, líneas y decisiones, con inmutabilidad en la base de datos

Esqueleto vertical (F0, desechable): una versión de presupuesto con sus líneas y
la decisión del cliente. Lo que se queda para F3 es el patrón de inmutabilidad
(arquitectura §3, RNF-11):

- un presupuesto enviado no cambia: un trigger rechaza tocar sus líneas y sus
  totales, aunque la aplicación tenga un fallo;
- la decisión es append-only por permisos: axtton_app no tiene UPDATE ni DELETE;
- el enlace de aprobación se guarda como hash, nunca el secreto.

Revision ID: a1f0c0de0002
Revises: a1f0c0de0001
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1f0c0de0002"
down_revision: str | None = "a1f0c0de0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enable_workshop_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY workshop_isolation ON {table}
            USING (workshop_id = ANY (app_current_workshops()))
            WITH CHECK (workshop_id = ANY (app_current_workshops()))
        """
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE quotes (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workshop_id uuid NOT NULL REFERENCES workshops (id),
            work_order_id uuid NOT NULL,
            status varchar(20) NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'sent', 'approved', 'rejected')),
            -- Se calcula y se GUARDA al enviar; nunca se recalcula (RNF-11, RNF-14).
            total_cents bigint,
            sent_at timestamptz,
            -- sha256 del enlace secreto. Si alguien lee la tabla, no puede aprobar.
            approval_token_hash bytea UNIQUE,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (id, workshop_id),
            FOREIGN KEY (work_order_id, workshop_id)
                REFERENCES work_orders (id, workshop_id),
            CHECK (status = 'draft' OR (total_cents IS NOT NULL AND sent_at IS NOT NULL))
        )
        """
    )
    # Como mucho una versión enviada a la vez por orden: lo impide la base de datos
    # aunque dos administradores envíen a la vez y el código falle.
    op.execute(
        "CREATE UNIQUE INDEX quotes_one_sent_per_work_order"
        " ON quotes (work_order_id) WHERE status = 'sent'"
    )
    enable_workshop_rls("quotes")

    op.execute(
        """
        CREATE TABLE quote_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workshop_id uuid NOT NULL REFERENCES workshops (id),
            quote_id uuid NOT NULL,
            description varchar(500) NOT NULL,
            quantity numeric(10, 3) NOT NULL CHECK (quantity > 0),
            unit_price_cents bigint NOT NULL CHECK (unit_price_cents >= 0),
            vat_bp smallint NOT NULL CHECK (vat_bp BETWEEN 0 AND 10000),
            -- Guardado al enviar, como el total del presupuesto.
            line_total_cents bigint,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            FOREIGN KEY (quote_id, workshop_id) REFERENCES quotes (id, workshop_id)
        )
        """
    )
    enable_workshop_rls("quote_lines")

    op.execute(
        """
        CREATE TABLE quote_decisions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workshop_id uuid NOT NULL REFERENCES workshops (id),
            quote_id uuid NOT NULL UNIQUE,
            outcome varchar(20) NOT NULL CHECK (outcome IN ('approved', 'rejected')),
            channel varchar(20) NOT NULL CHECK (channel IN ('portal', 'phone', 'in_person')),
            ip inet,
            user_agent varchar(500),
            decided_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            FOREIGN KEY (quote_id, workshop_id) REFERENCES quotes (id, workshop_id)
        )
        """
    )
    enable_workshop_rls("quote_decisions")
    # Append-only por permisos: los permisos por defecto dieron UPDATE y DELETE a
    # todos; aquí se quitan. Ni la aplicación ni el código de plataforma pueden
    # alterar una decisión (RNF-12).
    op.execute(
        "REVOKE UPDATE, DELETE ON quote_decisions FROM axtton_app, axtton_platform"
    )

    # Un presupuesto que ya no es borrador no admite cambios en sus líneas.
    op.execute(
        """
        CREATE FUNCTION quote_lines_frozen() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            parent_status varchar;
        BEGIN
            SELECT status INTO parent_status FROM quotes
            WHERE id = coalesce(NEW.quote_id, OLD.quote_id);
            IF parent_status IS DISTINCT FROM 'draft' THEN
                RAISE EXCEPTION 'quote % is %, its lines are frozen',
                    coalesce(NEW.quote_id, OLD.quote_id), parent_status
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN coalesce(NEW, OLD);
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER quote_lines_frozen
            BEFORE INSERT OR UPDATE OR DELETE ON quote_lines
            FOR EACH ROW EXECUTE FUNCTION quote_lines_frozen()
        """
    )

    # Una vez enviado, del presupuesto solo puede cambiar el estado, y solo
    # hacia una decisión. Total, fecha de envío y enlace quedan fijos.
    op.execute(
        """
        CREATE FUNCTION quotes_frozen_after_send() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status <> 'draft' THEN
                    RAISE EXCEPTION 'quote % is %, it cannot be deleted', OLD.id, OLD.status
                        USING ERRCODE = 'check_violation';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.status <> 'draft' AND (
                NEW.total_cents IS DISTINCT FROM OLD.total_cents
                OR NEW.sent_at IS DISTINCT FROM OLD.sent_at
                OR NEW.approval_token_hash IS DISTINCT FROM OLD.approval_token_hash
                OR NEW.work_order_id IS DISTINCT FROM OLD.work_order_id
                OR NOT (OLD.status = 'sent' AND NEW.status IN ('approved', 'rejected'))
            ) THEN
                RAISE EXCEPTION 'quote % is %, it cannot change', OLD.id, OLD.status
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER quotes_frozen_after_send
            BEFORE UPDATE OR DELETE ON quotes
            FOR EACH ROW EXECUTE FUNCTION quotes_frozen_after_send()
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE quote_decisions")
    op.execute("DROP TABLE quote_lines")
    op.execute("DROP TABLE quotes")
    op.execute("DROP FUNCTION quote_lines_frozen()")
    op.execute("DROP FUNCTION quotes_frozen_after_send()")
