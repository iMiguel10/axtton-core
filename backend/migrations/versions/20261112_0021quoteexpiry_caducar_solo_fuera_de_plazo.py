"""Una versión solo se marca caducada fuera de plazo (F5 paso 2, RF-33)

Desde F5, el worker escribe `expired` en las versiones enviadas cuya validez ya
pasó (`services/quotes.py::expire_overdue`). `quotes_frozen_after_send` ya
admitía el paso `sent → expired`, pero en cualquier momento: un fallo que la
marcara antes de tiempo le quitaría al cliente un presupuesto que aún puede
aceptar. Este trigger lo impide con cualquier rol, con la hora del servidor,
como hace `quote_decisions_only_when_sent` con las decisiones.

Va aparte, sin tocar `quotes_frozen_after_send`: así no hay que repetir su
cuerpo entero para añadir una condición.

Revision ID: 0021quoteexpiry
Revises: 0020linkpurge
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021quoteexpiry"
down_revision: str | None = "0020linkpurge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION quotes_expire_only_when_overdue() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.valid_until > clock_timestamp() THEN
                RAISE EXCEPTION 'quote % is still valid until %',
                    NEW.id, NEW.valid_until
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER quotes_expire_only_when_overdue
            BEFORE UPDATE ON quotes
            FOR EACH ROW
            WHEN (OLD.status = 'sent' AND NEW.status = 'expired')
            EXECUTE FUNCTION quotes_expire_only_when_overdue()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER quotes_expire_only_when_overdue ON quotes")
    op.execute("DROP FUNCTION quotes_expire_only_when_overdue()")
