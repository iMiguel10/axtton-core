"""Invitaciones de superadministrador (RF-110)

La tabla la generó --autogenerate y se revisó a mano. Lo que el generador no sabe
va al final: la tabla es de plataforma, sin taller ni RLS, así que se le retiran
a axtton_app los permisos que le dan por defecto los privilegios del dueño. Solo
app/platform/ (axtton_platform) la lee y escribe.

Revision ID: 0002sadminv
Revises: 0001f1base
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002sadminv"
down_revision: str | None = "0001f1base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "superadmin_invitations",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_superadmin_invitations_created_by_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_superadmin_invitations")),
        sa.UniqueConstraint(
            "token_hash", name=op.f("uq_superadmin_invitations_token_hash")
        ),
    )

    # --- A mano ---
    # Ni RLS (no es de un taller) ni acceso para la aplicación: que axtton_app no
    # pueda ni leerla hace que un fallo en /workshop no llegue nunca a estos tokens.
    op.execute("REVOKE ALL ON superadmin_invitations FROM axtton_app")


def downgrade() -> None:
    op.drop_table("superadmin_invitations")
