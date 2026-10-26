"""Tablas operativas del taller (F2): clientes, y después vehículos y órdenes.

Siguen la regla del multi-taller (arquitectura §3): workshop_id propio,
UNIQUE (id, workshop_id) para que las hijas puedan apuntar con FK compuestas, y
RLS forzada, que se añade a mano en la migración.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.work_orders import (
    StatusChangeCause,
    WorkOrderStatus,
    WorkOrderType,
    sql_in,
)
from app.models.base import Base, CreatedAtMixin, IdMixin, UpdatedAtMixin


class Client(IdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """Un cliente del taller (RF-10, especificación §4).

    Es de un solo taller: la misma persona en dos talleres son dos clientes. Su
    email, opcional, es el de acceso al portal (F4); sin email no hay portal.
    Nunca se borra: se archiva, y si lo pide, se anonimiza (RF-15) conservando la
    fila para que sus órdenes y presupuestos sigan apuntando a algo.
    """

    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        CheckConstraint("kind IN ('individual', 'company')", name="kind"),
        CheckConstraint("language IN ('es', 'en')", name="language"),
        # El email es la llave del portal: dos clientes del mismo taller con el
        # mismo email harían ambiguo a quién da acceso un enlace mágico (§7.2).
        # Se guarda ya en minúsculas, así que basta un índice sobre la columna.
        Index(
            "uq_clients_workshop_id_email",
            "workshop_id",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
        Index("ix_clients_workshop_id_name", "workshop_id", "name"),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    kind: Mapped[str] = mapped_column(String(20), server_default="individual")
    # Nombre y apellidos, o razón social si es una empresa.
    name: Mapped[str] = mapped_column(String(200))
    tax_id: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(320))
    address: Mapped[str | None] = mapped_column(String(300))
    # Notas internas: nunca salen del taller.
    notes: Mapped[str | None] = mapped_column(String(2000))
    # Idioma de los avisos y del portal.
    language: Mapped[str] = mapped_column(String(2), server_default="es")
    archived_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(server_default="1")

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class Vehicle(IdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """Un vehículo del taller (RF-11, RF-16).

    La matrícula se normaliza al guardar, no al buscar (arquitectura §3): el
    índice único va sobre `plate_normalized`, y `plate` conserva lo que se
    escribió para mostrarlo. El titular no es una columna: es el periodo abierto
    de `vehicle_ownerships`. Nunca se borra: sus órdenes apuntan a él.
    """

    __tablename__ = "vehicles"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        UniqueConstraint("workshop_id", "plate_normalized"),
        CheckConstraint(
            "fuel IN ('gasoline', 'diesel', 'hybrid', 'plug_in_hybrid',"
            " 'electric', 'lpg', 'cng', 'other')",
            name="fuel",
        ),
        CheckConstraint("year BETWEEN 1900 AND 2100", name="year"),
        CheckConstraint("next_service_km > 0", name="next_service_km"),
        # Un VIN repetido casi siempre es el mismo coche dado de alta dos veces
        # (con matrícula extranjera y luego española, por ejemplo).
        Index(
            "uq_vehicles_workshop_id_vin",
            "workshop_id",
            "vin",
            unique=True,
            postgresql_where=text("vin IS NOT NULL"),
        ),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    plate: Mapped[str] = mapped_column(String(20))
    plate_normalized: Mapped[str] = mapped_column(String(20))
    vin: Mapped[str | None] = mapped_column(String(17))
    # Texto libre con sugerencias de lo ya escrito en el taller (RF-11).
    make: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(60))
    year: Mapped[int | None] = mapped_column(SmallInteger)
    fuel: Mapped[str | None] = mapped_column(String(20))
    # Vencimientos (RF-16). La pantalla y los avisos llegan en F8.
    next_itv_date: Mapped[date | None]
    next_service_date: Mapped[date | None]
    next_service_km: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(server_default="1")

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class VehicleOwnership(IdMixin, CreatedAtMixin, Base):
    """Un periodo en el que un cliente fue el titular de un vehículo para el
    taller (RF-12, arquitectura §3). `ended_at` nulo es el titular actual.

    Los periodos no se borran, y uno cerrado no se vuelve a tocar: la migración
    deja a axtton_app actualizar solo `ended_at`, y un trigger rechaza cambiar
    un periodo ya cerrado. Que nunca haya dos titulares a la vez lo garantizan
    el índice parcial (uno abierto como mucho) y la restricción EXCLUDE de la
    migración (periodos que no se solapan), que el modelo no declara porque
    --autogenerate no la sabe comparar.
    """

    __tablename__ = "vehicle_ownerships"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        ForeignKeyConstraint(
            ["vehicle_id", "workshop_id"], ["vehicles.id", "vehicles.workshop_id"]
        ),
        ForeignKeyConstraint(
            ["client_id", "workshop_id"], ["clients.id", "clients.workshop_id"]
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at > started_at", name="ended_after_started"
        ),
        Index(
            "uq_vehicle_ownerships_current",
            "vehicle_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        Index("ix_vehicle_ownerships_client_id", "workshop_id", "client_id"),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    vehicle_id: Mapped[UUID]
    client_id: Mapped[UUID]
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]


class WorkOrderCounter(Base):
    """El último número de orden de cada taller y año (RF-21, arquitectura §3).

    No es una secuencia de Postgres (sería global, no por taller y año) ni un
    MAX(number) + 1 (daría el mismo número a dos órdenes abiertas a la vez): se
    pide con un único INSERT … ON CONFLICT DO UPDATE … RETURNING, que deja la
    fila bloqueada hasta el final de la transacción.
    """

    __tablename__ = "work_order_counters"
    __table_args__ = (CheckConstraint("last_number > 0", name="last_number"),)

    workshop_id: Mapped[UUID] = mapped_column(
        ForeignKey("workshops.id"), primary_key=True
    )
    year: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer)


class WorkOrder(IdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """Una visita del vehículo al taller (RF-20, especificación §4).

    Su cliente es el titular del vehículo al abrirla y no cambia nunca
    (invariante 7). Su estado es una copia del último cambio de su historial
    (invariante 5). Nunca se borra: una orden abierta por error se cancela.
    """

    __tablename__ = "work_orders"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        UniqueConstraint("workshop_id", "year", "number"),
        ForeignKeyConstraint(
            ["vehicle_id", "workshop_id"], ["vehicles.id", "vehicles.workshop_id"]
        ),
        ForeignKeyConstraint(
            ["client_id", "workshop_id"], ["clients.id", "clients.workshop_id"]
        ),
        ForeignKeyConstraint(
            ["responsible_employee_id", "workshop_id"],
            ["employees.id", "employees.workshop_id"],
        ),
        ForeignKeyConstraint(
            ["warranty_of_id", "workshop_id"],
            ["work_orders.id", "work_orders.workshop_id"],
        ),
        CheckConstraint(sql_in("type", WorkOrderType), name="type"),
        CheckConstraint(sql_in("status", WorkOrderStatus), name="status"),
        CheckConstraint(
            "no_quote_reason IN ('waiver', 'warranty', 'fixed_price')",
            name="no_quote_reason",
        ),
        # Solo una orden de garantía enlaza a la orden de la que viene (§6).
        CheckConstraint(
            "warranty_of_id IS NULL OR type = 'warranty'", name="warranty_of_type"
        ),
        CheckConstraint("odometer_km >= 0", name="odometer_km"),
        CheckConstraint("number > 0", name="number"),
        Index("ix_work_orders_workshop_id_vehicle_id", "workshop_id", "vehicle_id"),
        Index("ix_work_orders_workshop_id_client_id", "workshop_id", "client_id"),
        Index("ix_work_orders_workshop_id_status", "workshop_id", "status"),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    # El año del taller (su zona horaria), no el de UTC.
    year: Mapped[int] = mapped_column(SmallInteger)
    number: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(20))
    vehicle_id: Mapped[UUID]
    client_id: Mapped[UUID]
    responsible_employee_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(String(30))
    unrepaired: Mapped[bool] = mapped_column(server_default="false")
    no_quote_reason: Mapped[str | None] = mapped_column(String(20))
    warranty_of_id: Mapped[UUID | None]
    # Datos de recepción (RF-20).
    odometer_km: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(2000))
    expected_delivery_at: Mapped[datetime | None]
    # Quien trae el coche si no es el titular: un dato, sin acceso a nada.
    dropped_off_by_name: Mapped[str | None] = mapped_column(String(200))
    dropped_off_by_phone: Mapped[str | None] = mapped_column(String(30))
    # Daños visibles y objetos en el coche al recibirlo.
    reception_notes: Mapped[str | None] = mapped_column(String(2000))
    delivered_at: Mapped[datetime | None]
    # Para "las que llevan más tiempo paradas" (RF-24): cambios de estado y
    # trabajos registrados, no cualquier edición.
    last_activity_at: Mapped[datetime] = mapped_column(
        server_default=text("clock_timestamp()")
    )
    version: Mapped[int] = mapped_column(server_default="1")

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class WorkOrderStatusChange(IdMixin, CreatedAtMixin, Base):
    """Un cambio de estado de una orden, append-only (RNF-12).

    El orden del historial es `seq`, nunca la fecha (el reloj puede retroceder).
    La migración retira UPDATE y DELETE a axtton_app.
    """

    __tablename__ = "work_order_status_changes"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        ForeignKeyConstraint(
            ["work_order_id", "workshop_id"],
            ["work_orders.id", "work_orders.workshop_id"],
        ),
        ForeignKeyConstraint(
            ["employee_id", "workshop_id"], ["employees.id", "employees.workshop_id"]
        ),
        CheckConstraint(sql_in("to_status", WorkOrderStatus), name="to_status"),
        CheckConstraint(
            f"from_status IS NULL OR {sql_in('from_status', WorkOrderStatus)}",
            name="from_status",
        ),
        CheckConstraint(sql_in("cause", StatusChangeCause), name="cause"),
        # Solo el primero no viene de ningún estado.
        CheckConstraint(
            "(cause = 'opened') = (from_status IS NULL)", name="opened_from_nothing"
        ),
        CheckConstraint(
            "(cause = 'undo') = (undoes_seq IS NOT NULL)", name="undo_has_target"
        ),
        Index("ix_work_order_status_changes_work_order_id_seq", "work_order_id", "seq"),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    work_order_id: Mapped[UUID]
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    cause: Mapped[str] = mapped_column(String(20))
    undoes_seq: Mapped[int | None] = mapped_column(BigInteger)
    # Si este cambio envió un aviso al cliente: entonces no se puede deshacer.
    notified: Mapped[bool] = mapped_column(server_default="false")
    employee_id: Mapped[UUID | None]
    by_client: Mapped[bool] = mapped_column(server_default="false")
    note: Mapped[str | None] = mapped_column(Text)
