"""Borrar los enlaces del portal caducados (F5 paso 1)

El worker borra cada día los enlaces caducados hace más de unos días
(`domain/portal.py::LINK_RETENTION`), taller a taller y con axtton_app bajo RLS:
el planificador (`app/platform/scheduler.py`) solo dice qué talleres tienen algo
que borrar (arquitectura §4).

- axtton_app recibe `DELETE` sobre `portal_links`, que hasta ahora no tenía.
- Un trigger impide borrar, con cualquier rol, un enlace que aún no ha caducado:
  cuánto se guarda lo decide el código, pero nada puede quitarle a un cliente un
  enlace que todavía le vale. `TRUNCATE` (el de las pruebas y la demo, solo del
  dueño) no dispara triggers de fila.

Revision ID: 0020linkpurge
Revises: 0019portalslug
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020linkpurge"
down_revision: str | None = "0019portalslug"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION portal_links_delete_only_expired() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.expires_at >= clock_timestamp() THEN
                RAISE EXCEPTION 'portal link % has not expired yet', OLD.id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN OLD;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER portal_links_delete_only_expired
            BEFORE DELETE ON portal_links
            FOR EACH ROW EXECUTE FUNCTION portal_links_delete_only_expired()
        """
    )
    op.execute("GRANT DELETE ON portal_links TO axtton_app")


def downgrade() -> None:
    op.execute("REVOKE DELETE ON portal_links FROM axtton_app")
    op.execute("DROP TRIGGER portal_links_delete_only_expired ON portal_links")
    op.execute("DROP FUNCTION portal_links_delete_only_expired()")
