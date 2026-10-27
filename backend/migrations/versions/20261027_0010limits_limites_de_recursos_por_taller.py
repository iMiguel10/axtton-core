"""Límites de recursos por taller (F2 paso 9b, especificación §10, RF-114)

Hasta aquí solo se limitaba quién entra (`max_employees_with_access`, F1). Se
añaden las fichas del personal, los clientes, los vehículos y las órdenes al
mes, con los valores del plan básico (domain/limits.py::BASIC_PLAN) como valor
por defecto: un taller nuevo nace con ellos y el superadministrador los ajusta
por taller. El de acceso baja de 20 a 5, el del plan básico, para los talleres
que se den de alta desde ahora; los que ya existen conservan su valor.

Solo la plataforma escribe en `workshops` (`axtton_app` no tiene UPDATE, migración
0003grants): el taller lee sus límites, no los cambia.

Alembic no detecta los CHECK ni el cambio de valor por defecto: van a mano.

Revision ID: 0010limits
Revises: 0009payment
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010limits"
down_revision: str | None = "0009payment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW = (
    ("max_employees", sa.SmallInteger(), "10"),
    ("max_clients", sa.Integer(), "1000"),
    ("max_vehicles", sa.Integer(), "1500"),
    ("max_orders_per_month", sa.Integer(), "200"),
)


def upgrade() -> None:
    for name, type_, default in NEW:
        op.add_column(
            "workshops",
            sa.Column(name, type_, server_default=default, nullable=False),
        )
        op.create_check_constraint(
            op.f(f"ck_workshops_{name}"), "workshops", f"{name} > 0"
        )
    op.alter_column("workshops", "max_employees_with_access", server_default="5")


def downgrade() -> None:
    op.alter_column("workshops", "max_employees_with_access", server_default="20")
    for name, _, _ in reversed(NEW):
        op.drop_constraint(op.f(f"ck_workshops_{name}"), "workshops")
        op.drop_column("workshops", name)
