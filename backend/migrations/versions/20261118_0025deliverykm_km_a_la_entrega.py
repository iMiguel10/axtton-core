"""Los km a la entrega (F6 paso 4, RF-53)

El resumen de entrega lleva la garantía de la reparación: como mínimo 3 meses o
2.000 km desde la entrega, lo que llegue antes. Para los km hacen falta los del
coche al entregarlo, que hasta ahora no se anotaban: `delivered_odometer_km`, que
se escribe solo al pasar a entregada y nunca por debajo de los de entrada (un
CHECK). Como la orden entregada ya no se edita (RF-26), no cambian después.

Revision ID: 0025deliverykm
Revises: 0024receptionsheets
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025deliverykm"
down_revision: str | None = "0024receptionsheets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_orders", sa.Column("delivered_odometer_km", sa.Integer(), nullable=True)
    )
    op.create_check_constraint(
        "delivered_odometer_km",
        "work_orders",
        "delivered_odometer_km IS NULL OR (status = 'delivered'"
        " AND delivered_odometer_km >= coalesce(odometer_km, 0))",
    )
    # La escribe la aplicación al entregar (permiso por columna, 0011ordercols).
    op.execute("GRANT UPDATE (delivered_odometer_km) ON work_orders TO axtton_app")


def downgrade() -> None:
    op.execute("REVOKE UPDATE (delivered_odometer_km) ON work_orders FROM axtton_app")
    op.drop_constraint("delivered_odometer_km", "work_orders", type_="check")
    op.drop_column("work_orders", "delivered_odometer_km")
