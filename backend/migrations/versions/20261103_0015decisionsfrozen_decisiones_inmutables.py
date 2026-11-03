"""Decisiones inmutables para cualquier rol (F3 cierre, invariante 6)

Una decisión registrada no se modifica jamás. Hasta ahora lo guardaban solo los
permisos (0013quotes revoca `UPDATE` y `DELETE` a `axtton_app` y a
`axtton_platform`), pero el dueño de las tablas podía cambiar el resultado o la
fecha, o borrarla. Las versiones enviadas ya estaban protegidas con un trigger
para cualquier rol; las decisiones, ahora también: `quote_decisions_frozen`
rechaza todo `UPDATE` y `DELETE`.

`TRUNCATE` no dispara triggers de fila: `reset_data.py` y la demo siguen
pudiendo vaciar las tablas. La demo, que mueve hacia atrás la hora de sus
decisiones, desactiva el trigger dentro de su transacción, como hace con el
de las versiones enviadas.

Revision ID: 0015decisionsfrozen
Revises: 0014quotepdf
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015decisionsfrozen"
down_revision: str | None = "0014quotepdf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION quote_decisions_frozen() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'the decision on quote % cannot change', OLD.quote_id
                USING ERRCODE = 'check_violation';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER quote_decisions_frozen
            BEFORE UPDATE OR DELETE ON quote_decisions
            FOR EACH ROW EXECUTE FUNCTION quote_decisions_frozen()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER quote_decisions_frozen ON quote_decisions")
    op.execute("DROP FUNCTION quote_decisions_frozen()")
