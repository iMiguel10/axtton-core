"""Tablas de plataforma y de personal (F1).

`users` es la única tabla sin taller: una cuenta existe por encima de los
talleres. Todas las demás llevan workshop_id, UNIQUE (id, workshop_id), FK
compuestas y RLS forzada (CLAUDE.md, convenciones).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, UpdatedAtMixin


class User(IdMixin, CreatedAtMixin, Base):
    """Una cuenta de acceso. No guarda email ni contraseña: viven en SuperTokens."""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint("kind IN ('staff', 'superadmin')", name="kind"),)

    supertokens_user_id: Mapped[str] = mapped_column(String(128), unique=True)
    # Un superadministrador nunca es empleado de un taller (arquitectura §2).
    kind: Mapped[str] = mapped_column(String(20))


class Workshop(IdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "workshops"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="status"),
        CheckConstraint("default_vat_bp BETWEEN 0 AND 10000", name="default_vat_bp"),
        # Mínimo legal de validez del presupuesto (RF-33).
        CheckConstraint(
            "quote_validity_business_days >= 12", name="quote_validity_business_days"
        ),
        CheckConstraint(
            "signature_retention_months BETWEEN 1 AND 60",
            name="signature_retention_months",
        ),
        CheckConstraint(
            "max_employees_with_access > 0", name="max_employees_with_access"
        ),
    )

    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(200))
    tax_id: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(300))
    phone: Mapped[str | None] = mapped_column(String(30))
    # Dirección de respuesta de los avisos al cliente (RF-68).
    reply_to_email: Mapped[str | None] = mapped_column(String(320))
    # Obligatorio en los presupuestos (RD 1457/1986, RF-37).
    industrial_registry_number: Mapped[str | None] = mapped_column(String(50))
    # Zona horaria del taller (R10): las fechas se guardan en UTC y se muestran en esta.
    timezone: Mapped[str] = mapped_column(String(64), server_default="Europe/Madrid")
    status: Mapped[str] = mapped_column(String(20), server_default="active")
    default_vat_bp: Mapped[int] = mapped_column(SmallInteger, server_default="2100")
    quote_validity_business_days: Mapped[int] = mapped_column(
        SmallInteger, server_default="12"
    )
    mechanics_see_sale_prices: Mapped[bool] = mapped_column(server_default="true")
    signature_retention_months: Mapped[int] = mapped_column(
        SmallInteger, server_default="6"
    )
    # Límite de cuenta que el superadministrador puede ajustar (§10, RF-114).
    max_employees_with_access: Mapped[int] = mapped_column(
        SmallInteger, server_default="20"
    )
    version: Mapped[int] = mapped_column(server_default="1")

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class Employee(IdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """La ficha de una persona del personal en un taller (especificación §4).

    El rol vive aquí, no en el usuario: una persona puede ser admin en un taller
    y mecánico en otro. El usuario es opcional: un mecánico que nunca entra en la
    aplicación existe igual.
    """

    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        # Como mucho un empleado por usuario y taller. Los NULL no chocan entre
        # sí, así que puede haber muchas fichas sin acceso.
        UniqueConstraint("workshop_id", "user_id"),
        CheckConstraint("role IN ('admin', 'mechanic')", name="role"),
        CheckConstraint("hourly_cost_cents >= 0", name="hourly_cost_cents"),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))
    hourly_cost_cents: Mapped[int | None] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(server_default="true")
    version: Mapped[int] = mapped_column(server_default="1")

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class Invitation(IdMixin, CreatedAtMixin, Base):
    """Invitación para dar acceso a una ficha de empleado (RF-04).

    Del enlace solo se guarda el hash, como en F0 con el presupuesto.
    """

    __tablename__ = "invitations"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        ForeignKeyConstraint(
            ["employee_id", "workshop_id"], ["employees.id", "employees.workshop_id"]
        ),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    employee_id: Mapped[UUID]
    email: Mapped[str] = mapped_column(String(320))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    expires_at: Mapped[datetime]
    accepted_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))


class SuperadminInvitation(IdMixin, CreatedAtMixin, Base):
    """Invitación para ser superadministrador (RF-110).

    De la plataforma, no de un taller: sin workshop_id ni RLS, y solo el rol de
    plataforma la lee (la migración se la retira a axtton_app). Del enlace solo
    se guarda el hash, como en las de empleados.
    """

    __tablename__ = "superadmin_invitations"

    email: Mapped[str] = mapped_column(String(320))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    expires_at: Mapped[datetime]
    accepted_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))


class AuditEntry(IdMixin, CreatedAtMixin, Base):
    """Registro de acciones sensibles (RNF-16). Append-only por permisos.

    workshop_id es nulo en las acciones de plataforma (alta de un taller): esas
    filas no las ve nunca un taller, porque NULL no está en ningún conjunto de
    talleres de RLS.
    """

    __tablename__ = "audit_log"

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    workshop_id: Mapped[UUID | None] = mapped_column(ForeignKey("workshops.id"))
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[UUID | None]
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
