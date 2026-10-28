"""Columnas actualizables de work_orders (cierre de F2, invariante 7)

Hasta aquí `axtton_app` solo tenía quitado el DELETE de `work_orders`, así que
un UPDATE podía cambiar el cliente, el vehículo, el número o el año de una orden
ya abierta: el invariante 7 ("el cliente de una orden es el titular al abrirla")
lo protegía solo el código, y en F4 el portal dará acceso por
`work_orders.client_id`. Lo encontró qa-verifier al cerrar F2.

Como en `vehicle_ownerships` y `work_entries`, el permiso pasa a ser por
columna: lo que fija la apertura (taller, año, número, tipo, vehículo, cliente,
garantía de origen, creación) no se puede cambiar con ningún UPDATE de la
aplicación. La plataforma (`axtton_platform`) conserva el permiso entero: la
usa el script de la demo para mover fechas y renumerar.

Revision ID: 0011ordercols
Revises: 0010limits
Create Date: 2026-10-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011ordercols"
down_revision: str | None = "0010limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Lo que cambia durante la vida de una orden: la recepción y el responsable, el
# estado y lo que lo acompaña, el cobro y el bloqueo optimista.
UPDATABLE = (
    "responsible_employee_id",
    "status",
    "unrepaired",
    "no_quote_reason",
    "odometer_km",
    "reason",
    "expected_delivery_at",
    "dropped_off_by_name",
    "dropped_off_by_phone",
    "reception_notes",
    "delivered_at",
    "payment_status",
    "payment_method",
    "paid_amount_cents",
    "paid_on",
    "last_activity_at",
    "version",
    "updated_at",
)


def upgrade() -> None:
    op.execute("REVOKE UPDATE ON work_orders FROM axtton_app")
    op.execute(f"GRANT UPDATE ({', '.join(UPDATABLE)}) ON work_orders TO axtton_app")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE ({', '.join(UPDATABLE)}) ON work_orders FROM axtton_app")
    op.execute("GRANT UPDATE ON work_orders TO axtton_app")
