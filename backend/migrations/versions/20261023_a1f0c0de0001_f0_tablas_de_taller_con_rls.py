"""F0: talleres, clientes, vehículos y órdenes, con RLS

Esqueleto vertical (F0, desechable): las tablas son mínimas y se rehacen en F1 y
F2. Lo que NO es desechable es el patrón de aislamiento, que se queda tal cual:

- toda tabla de taller lleva workshop_id y UNIQUE (id, workshop_id);
- sus FK son compuestas, (padre_id, workshop_id), para que la base de datos
  impida enlazar filas de dos talleres;
- RLS activada Y forzada, con la misma política en todas (arquitectura §4).

Revision ID: a1f0c0de0001
Revises:
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1f0c0de0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enable_workshop_rls(table: str, column: str = "workshop_id") -> None:
    """Activa y FUERZA RLS en una tabla de taller y le pone la política común.

    FORCE es lo que hace que la política se aplique también al dueño de la tabla
    (axtton_owner). Sin FORCE, el dueño la ignora sin avisar.
    """
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY workshop_isolation ON {table}
            USING ({column} = ANY (app_current_workshops()))
            WITH CHECK ({column} = ANY (app_current_workshops()))
        """
    )


def upgrade() -> None:
    # Los talleres de la transacción. current_setting(..., true) devuelve NULL si
    # nadie lo fijó, y entonces el resultado es un array vacío: la consulta no ve
    # ninguna fila. Un olvido falla cerrado. STABLE: Postgres puede evaluarla una
    # vez por consulta en lugar de una por fila.
    op.execute(
        """
        CREATE FUNCTION app_current_workshops() RETURNS uuid[]
        LANGUAGE sql STABLE AS $$
            SELECT coalesce(
                nullif(current_setting('app.workshop_ids', true), '')::uuid[],
                '{}'::uuid[]
            )
        $$
        """
    )

    op.execute(
        """
        CREATE TABLE workshops (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name varchar(200) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )
        """
    )
    # En workshops la columna del taller es su propio id.
    enable_workshop_rls("workshops", column="id")

    op.execute(
        """
        CREATE TABLE clients (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workshop_id uuid NOT NULL REFERENCES workshops (id),
            name varchar(200) NOT NULL,
            email varchar(320),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (id, workshop_id)
        )
        """
    )
    enable_workshop_rls("clients")

    op.execute(
        """
        CREATE TABLE vehicles (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workshop_id uuid NOT NULL REFERENCES workshops (id),
            plate varchar(20) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (id, workshop_id),
            UNIQUE (workshop_id, plate)
        )
        """
    )
    enable_workshop_rls("vehicles")

    op.execute(
        """
        CREATE TABLE work_orders (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workshop_id uuid NOT NULL REFERENCES workshops (id),
            vehicle_id uuid NOT NULL,
            client_id uuid NOT NULL,
            status varchar(30) NOT NULL DEFAULT 'recibida',
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (id, workshop_id),
            -- FK compuestas: el vehículo y el cliente tienen que ser del MISMO taller
            -- que la orden. Con una FK simple (vehicle_id) bastaría con que existieran.
            FOREIGN KEY (vehicle_id, workshop_id) REFERENCES vehicles (id, workshop_id),
            FOREIGN KEY (client_id, workshop_id) REFERENCES clients (id, workshop_id)
        )
        """
    )
    enable_workshop_rls("work_orders")


def downgrade() -> None:
    op.execute("DROP TABLE work_orders")
    op.execute("DROP TABLE vehicles")
    op.execute("DROP TABLE clients")
    op.execute("DROP TABLE workshops")
    op.execute("DROP FUNCTION app_current_workshops()")
