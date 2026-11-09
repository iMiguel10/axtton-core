"""La cerradura del portal de cada cliente (F4 paso 2, RF-47)

`portal_epoch` sube al cambiar el email del cliente o al anonimizarlo. Cada sesión
del portal lleva el valor que tenía al crearse, y la dependencia del portal los
compara en cada petición: una sesión con otro valor deja de valer al instante, sin
esperar a que caduque su token de acceso (hasta 5 minutos) y aunque se haya creado
después de revocar las demás.

Revision ID: 0017portalepoch
Revises: 0016portallinks
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017portalepoch"
down_revision: str | None = "0016portallinks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column("portal_epoch", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_clients_portal_epoch"), "clients", "portal_epoch > 0"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_clients_portal_epoch"), "clients", type_="check")
    op.drop_column("clients", "portal_epoch")
