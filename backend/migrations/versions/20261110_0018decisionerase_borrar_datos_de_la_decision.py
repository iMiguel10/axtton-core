"""Lo personal de una decisión del portal se borra al anonimizar (F4 paso 5, RNF-40)

Una decisión tomada en el portal guarda la IP y el navegador del cliente (RF-36) y
el motivo que escribió al rechazar (RF-34). Son datos personales, y tras anonimizar
a un cliente no puede quedar ninguno (RF-15, RNF-40). Las decisiones no se tocan
(invariante 6), así que el trigger admite una única excepción: vaciar esas tres
columnas de una decisión del portal cuyo cliente ya esté anonimizado. Lo que se
decidió (la versión, el resultado, el canal y la fecha) sigue sin poder cambiar.

La de `axtton_app` es una concesión por columna: las demás siguen sin permiso.

Revision ID: 0018decisionerase
Revises: 0017portalepoch
Create Date: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018decisionerase"
down_revision: str | None = "0017portalepoch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Con dos IF: un DELETE no tiene NEW, y PL/pgSQL resuelve toda la expresión.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION quote_decisions_frozen() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF OLD.channel = 'portal'
                    AND NEW.ip IS NULL
                    AND NEW.user_agent IS NULL
                    AND NEW.note IS NULL
                    AND (NEW.id, NEW.workshop_id, NEW.quote_id, NEW.outcome,
                         NEW.channel, NEW.recorded_by_employee_id, NEW.decided_at,
                         NEW.created_at)
                        IS NOT DISTINCT FROM
                        (OLD.id, OLD.workshop_id, OLD.quote_id, OLD.outcome,
                         OLD.channel, OLD.recorded_by_employee_id, OLD.decided_at,
                         OLD.created_at)
                    AND EXISTS (
                        SELECT 1
                        FROM quotes q
                        JOIN work_orders o ON o.id = q.work_order_id
                        JOIN clients c ON c.id = o.client_id
                        WHERE q.id = OLD.quote_id AND c.anonymized_at IS NOT NULL
                    )
                THEN
                    RETURN NEW;
                END IF;
            END IF;
            RAISE EXCEPTION 'the decision on quote % cannot change', OLD.quote_id
                USING ERRCODE = 'check_violation';
        END
        $$
        """
    )
    op.execute("GRANT UPDATE (ip, user_agent, note) ON quote_decisions TO axtton_app")


def downgrade() -> None:
    op.execute(
        "REVOKE UPDATE (ip, user_agent, note) ON quote_decisions FROM axtton_app"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION quote_decisions_frozen() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'the decision on quote % cannot change', OLD.quote_id
                USING ERRCODE = 'check_violation';
        END
        $$
        """
    )
