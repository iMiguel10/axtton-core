"""Permisos mínimos para los roles de la aplicación (cierre de F1)

Los privilegios por defecto del dueño (deploy/postgres/initdb/01-roles.sh) dan
SELECT, INSERT, UPDATE y DELETE en toda tabla nueva a axtton_app y axtton_platform.
Es cómodo, pero da de más. qa-verifier lo encontró al cerrar F1:

- `users` no tiene RLS, y axtton_app podía hacer `UPDATE users SET kind =
  'superadmin'`: un fallo en /workshop convertiría a alguien del personal en
  superadministrador en su siguiente inicio de sesión. La aplicación solo lee
  `users` y da de alta personal (INSERT); lo demás es de la plataforma.
- `workshops`: axtton_app podía cambiar el estado y los límites de su propio
  taller, que son cosa del superadministrador (RF-113, RF-114). La aplicación
  solo lo lee. Cuando el administrador edite los datos de su taller (RF-02), se le
  dará UPDATE solo sobre esas columnas.
- `alembic_version`: ninguna de las dos debería poder cambiar qué migraciones
  constan como aplicadas.

Revision ID: 0003grants
Revises: 0002sadminv
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003grants"
down_revision: str | None = "0002sadminv"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("REVOKE UPDATE, DELETE ON users FROM axtton_app")
    op.execute("REVOKE INSERT, UPDATE, DELETE ON workshops FROM axtton_app")
    op.execute("REVOKE ALL ON alembic_version FROM axtton_app, axtton_platform")


def downgrade() -> None:
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON alembic_version"
        " TO axtton_app, axtton_platform"
    )
    op.execute("GRANT INSERT, UPDATE, DELETE ON workshops TO axtton_app")
    op.execute("GRANT UPDATE, DELETE ON users TO axtton_app")
