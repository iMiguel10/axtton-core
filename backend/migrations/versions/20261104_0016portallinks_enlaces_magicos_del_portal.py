"""Enlaces mágicos del portal (F4 paso 1, RF-40, RF-45, decisión 0006)

La tabla la generó --autogenerate desde app/models y se revisó a mano. Lo
añadido a mano:

- RLS forzada con la política común: el enlace es de un taller, y consumirlo con
  otro taller fijado no lo encuentra (T5).
- De un enlace, axtton_app solo puede escribir cómo se cerró (`used_at` o
  `revoked_at`), nunca borrarlo.
- Un trigger impide tocar un enlace ya cerrado, con cualquier rol: un enlace
  usado no vuelve a valer (T6, RNF-04).

Revision ID: 0016portallinks
Revises: 0015decisionsfrozen
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016portallinks"
down_revision: str | None = "0015decisionsfrozen"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portal_links",
        sa.Column("workshop_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
            "expires_at > created_at",
            name=op.f("ck_portal_links_expires_after_creation"),
        ),
        sa.CheckConstraint(
            "used_at IS NULL OR revoked_at IS NULL",
            name=op.f("ck_portal_links_closed_once"),
        ),
        sa.ForeignKeyConstraint(
            ["client_id", "workshop_id"],
            ["clients.id", "clients.workshop_id"],
            name=op.f("fk_portal_links_client_id_workshop_id_clients"),
        ),
        sa.ForeignKeyConstraint(
            ["workshop_id"],
            ["workshops.id"],
            name=op.f("fk_portal_links_workshop_id_workshops"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portal_links")),
        sa.UniqueConstraint(
            "id", "workshop_id", name=op.f("uq_portal_links_id_workshop_id")
        ),
        sa.UniqueConstraint("token_hash", name=op.f("uq_portal_links_token_hash")),
    )
    op.create_index(
        "ix_portal_links_workshop_id_client_id",
        "portal_links",
        ["workshop_id", "client_id"],
        unique=False,
    )

    # Un enlace cerrado (usado o revocado) no se vuelve a tocar, con ningún rol:
    # si alguien pudiera poner `used_at` a NULL, el enlace volvería a valer.
    op.execute(
        """
        CREATE FUNCTION portal_links_closed_frozen() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.used_at IS NOT NULL OR OLD.revoked_at IS NOT NULL THEN
                RAISE EXCEPTION 'portal link % is already closed', OLD.id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER portal_links_closed_frozen
            BEFORE UPDATE ON portal_links
            FOR EACH ROW EXECUTE FUNCTION portal_links_closed_frozen()
        """
    )

    op.execute("ALTER TABLE portal_links ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE portal_links FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY workshop_isolation ON portal_links
            USING (workshop_id = ANY (app_current_workshops()))
            WITH CHECK (workshop_id = ANY (app_current_workshops()))
        """
    )

    # Solo se cierra; nunca se borra ni se reescribe.
    op.execute("REVOKE UPDATE, DELETE ON portal_links FROM axtton_app")
    op.execute("GRANT UPDATE (used_at, revoked_at) ON portal_links TO axtton_app")


def downgrade() -> None:
    op.drop_index("ix_portal_links_workshop_id_client_id", table_name="portal_links")
    op.drop_table("portal_links")
    op.execute("DROP FUNCTION portal_links_closed_frozen()")
