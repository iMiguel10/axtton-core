"""El nombre corto del taller en la dirección del portal (F4 paso 7, decisión 0007)

`workshops.portal_slug`: lo elige el administrador del taller y da la dirección
`/portal/{nombre}`. Único en toda la instalación (el índice único es la última
palabra: dos talleres que lo eligen a la vez, el segundo recibe un 409) y con el
formato de una dirección, que el CHECK guarda en minúsculas: así "sin distinguir
mayúsculas" es lo mismo que "igual". Las palabras reservadas (las rutas del
portal) las comprueba `domain/portal.py`, porque cambian con el portal.

`axtton_app` puede actualizar la columna (lo hace el administrador en /settings);
encontrar un taller por ella cruza talleres y va por `app/platform/portal_entry.py`.

Revision ID: 0019portalslug
Revises: 0018decisionerase
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019portalslug"
down_revision: str | None = "0018decisionerase"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workshops", sa.Column("portal_slug", sa.String(40), nullable=True))
    op.create_unique_constraint(
        op.f("uq_workshops_portal_slug"), "workshops", ["portal_slug"]
    )
    op.create_check_constraint(
        "portal_slug",
        "workshops",
        "portal_slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'"
        " AND length(portal_slug) BETWEEN 3 AND 40",
    )
    op.execute("GRANT UPDATE (portal_slug) ON workshops TO axtton_app")


def downgrade() -> None:
    op.execute("REVOKE UPDATE (portal_slug) ON workshops FROM axtton_app")
    op.drop_constraint("ck_workshops_portal_slug", "workshops", type_="check")
    op.drop_constraint(op.f("uq_workshops_portal_slug"), "workshops", type_="unique")
    op.drop_column("workshops", "portal_slug")
