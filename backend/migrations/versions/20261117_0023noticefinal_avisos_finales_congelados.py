"""Un aviso terminado no cambia nada (cierre de F5)

`notifications_transitions` (0022outbox) hace finales los estados `sent`,
`unknown`, `cancelled` y `skipped`: ninguno vuelve atrás. Pero con el estado
igual dejaba reescribir el resto de la fila, y `axtton_app` puede escribir esas
columnas: la hora de envío, el motivo o el código SMTP de un aviso ya terminado,
que es el historial que ve el taller (RF-69). Lo encontró qa-verifier al cerrar
F5. Este trigger lo impide con cualquier rol: de un aviso terminado solo puede
cambiar `updated_at`.

Va aparte, como `quotes_expire_only_when_overdue` (0021quoteexpiry): así no hay
que repetir el cuerpo entero de `notifications_transitions`.

Revision ID: 0023noticefinal
Revises: 0022outbox
Create Date: 2026-11-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023noticefinal"
down_revision: str | None = "0022outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION notifications_final_frozen() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            -- Cambiar de estado lo vigila notifications_transitions; aquí, lo
            -- que se reescribe sin cambiarlo.
            IF OLD.status IN ('sent', 'unknown', 'cancelled', 'skipped')
               AND NEW.status = OLD.status
               AND (to_jsonb(NEW) - 'updated_at')
                   IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at') THEN
                RAISE EXCEPTION 'notification % is % and cannot change',
                    OLD.id, OLD.status
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER notifications_final_frozen
            BEFORE UPDATE ON notifications
            FOR EACH ROW EXECUTE FUNCTION notifications_final_frozen()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER notifications_final_frozen ON notifications")
    op.execute("DROP FUNCTION notifications_final_frozen()")
