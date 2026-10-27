"""Administración de talleres por el superadministrador (RF-110 a RF-114).

Usa el rol de plataforma porque trabaja con varios talleres a la vez. Nunca
devuelve datos operativos de un taller (clientes, órdenes, empleados uno a uno):
solo datos de cuenta y recuentos (RNF-08).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.tokens import hash_token, new_token
from app.domain.emails import invitation_email
from app.domain.invitations import INVITATION_VALIDITY, invitation_path
from app.domain.limits import Resource, limit_column
from app.infra.email import EmailSender, compose
from app.models import (
    AuditEntry,
    Client,
    Employee,
    Invitation,
    User,
    Vehicle,
    WorkOrder,
    Workshop,
)
from app.platform.db import platform_transaction


async def _user_id(session: AsyncSession, supertokens_user_id: str) -> UUID | None:
    return await session.scalar(
        select(User.id).where(User.supertokens_user_id == supertokens_user_id)
    )


@dataclass(frozen=True)
class CreatedWorkshop:
    workshop_id: UUID
    invitation_email_sent: bool


async def create_workshop(
    *,
    name: str,
    admin_name: str,
    admin_email: str,
    created_by: str,
    email_sender: EmailSender,
) -> CreatedWorkshop:
    """Da de alta un taller con su primer administrador e invita a este por email.

    El email se envía DESPUÉS del commit: si la transacción fallara, no debe
    llegarle a nadie una invitación a un taller que no existe. Si lo que falla es
    el envío, el taller y la invitación ya existen y se puede reenviar (paso 4).
    """
    token = new_token()
    async with platform_transaction() as session:
        # Taller único (RF-111): se crea una vez y nunca más. El bloqueo pone en
        # fila las altas: sin él, dos a la vez cuentan cero y crean dos talleres.
        if get_settings().installation_mode == "single":
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": "workshop_creation"},
            )
            if await session.scalar(select(func.count()).select_from(Workshop)):
                raise ConflictError("single_workshop_installation")

        workshop = Workshop(name=name)
        session.add(workshop)
        await session.flush()  # para tener workshop.id

        admin = Employee(workshop_id=workshop.id, name=admin_name, role="admin")
        session.add(admin)
        await session.flush()

        session.add(
            Invitation(
                workshop_id=workshop.id,
                employee_id=admin.id,
                email=admin_email,
                token_hash=hash_token(token),
                expires_at=datetime.now(UTC) + INVITATION_VALIDITY,
                created_by_user_id=await _user_id(session, created_by),
            )
        )
        # Acción de plataforma: workshop_id nulo, así que el taller no la ve.
        # Sin el email del administrador: la auditoría no guarda datos personales
        # que no necesite.
        session.add(
            AuditEntry(
                actor_user_id=await _user_id(session, created_by),
                action="workshop_created",
                target_type="workshop",
                target_id=workshop.id,
                details={"name": name},
            )
        )
        workshop_id = workshop.id

    sent = False
    if email_sender.enabled:
        content = invitation_email(
            employee_name=admin_name,
            workshop_name=name,
            link=get_settings().app_url + invitation_path(workshop_id, token),
            first_admin=True,
        )
        await email_sender.send(compose(admin_email, content))
        sent = True
    return CreatedWorkshop(workshop_id=workshop_id, invitation_email_sent=sent)


@dataclass(frozen=True)
class WorkshopSummary:
    id: UUID
    name: str
    status: str
    created_at: datetime
    max_employees_with_access: int
    employees_with_access: int
    pending_invitations: int
    # Cada límite (§10) con lo gastado: solo números, nada operativo.
    limits: dict[Resource, tuple[int, int]]
    # Nombres de los administradores activos, con acceso o con la invitación
    # pendiente (RF-114). Solo el nombre: ni email ni nada de su trabajo.
    admins: list[str]


async def list_workshops() -> list[WorkshopSummary]:
    """Talleres con datos de cuenta, sus administradores y el uso respecto a los
    límites (RF-114). Ningún dato operativo (RNF-08)."""
    with_access = (
        select(func.count())
        .where(
            Employee.workshop_id == Workshop.id,
            Employee.user_id.is_not(None),
            Employee.active,
        )
        .scalar_subquery()
    )
    pending = (
        select(func.count())
        .where(
            Invitation.workshop_id == Workshop.id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > func.clock_timestamp(),
        )
        .scalar_subquery()
    )
    async with platform_transaction() as session:
        rows = (
            await session.execute(
                select(
                    Workshop.id,
                    Workshop.name,
                    Workshop.status,
                    Workshop.created_at,
                    Workshop.max_employees_with_access,
                    with_access.label("with_access"),
                    pending.label("pending"),
                    *(
                        getattr(Workshop, limit_column(r)).label(f"limit_{r.value}")
                        for r in Resource
                    ),
                    *(
                        used.label(f"used_{r.value}")
                        for r, used in _usage_columns().items()
                    ),
                ).order_by(Workshop.created_at)
            )
        ).all()
        admins: dict[UUID, list[str]] = {}
        for workshop_id, name in await session.execute(
            select(Employee.workshop_id, Employee.name)
            .where(Employee.role == "admin", Employee.active)
            .order_by(Employee.name)
        ):
            admins.setdefault(workshop_id, []).append(name)
        return [
            WorkshopSummary(
                id=row.id,
                name=row.name,
                status=row.status,
                created_at=row.created_at,
                max_employees_with_access=row.max_employees_with_access,
                employees_with_access=row.with_access,
                pending_invitations=row.pending,
                limits={
                    r: (
                        getattr(row, f"used_{r.value}"),
                        getattr(row, f"limit_{r.value}"),
                    )
                    for r in Resource
                },
                admins=admins.get(row.id, []),
            )
            for row in rows
        ]


async def update_workshop(
    workshop_id: UUID,
    *,
    status: str | None,
    limits: dict[Resource, int],
    updated_by: str,
) -> None:
    """Desactivar o reactivar (RF-113) y ajustar los límites (RF-114, §10).

    Bajar un límite por debajo de lo ya gastado se admite: no borra nada, solo
    impide crear más hasta volver a tener hueco.

    Desactivar no borra nada: corta el acceso, y reactivar lo devuelve todo como
    estaba. El efecto sobre las sesiones del taller se comprueba en cada petición
    (paso 4).
    """
    async with platform_transaction() as session:
        workshop = await session.get(Workshop, workshop_id)
        if workshop is None:
            raise NotFoundError("workshop_not_found")
        changes: dict[str, object] = {}
        if status is not None and status != workshop.status:
            changes["status"] = [workshop.status, status]
            workshop.status = status
        for resource, value in limits.items():
            column = limit_column(resource)
            if value != getattr(workshop, column):
                # La clave es la columna: max_clients, max_orders_per_month…
                changes[column] = [getattr(workshop, column), value]
                setattr(workshop, column, value)
        if changes:
            session.add(
                AuditEntry(
                    actor_user_id=await _user_id(session, updated_by),
                    action="workshop_updated",
                    target_type="workshop",
                    target_id=workshop_id,
                    details=changes,
                )
            )


def _usage_columns() -> dict[Resource, Any]:
    """Lo gastado de cada límite, una subconsulta por taller (RF-114). Las mismas
    reglas que repositories/limits.py::usage, pero cruzando talleres: aquí no hay
    RLS (rol de plataforma), así que cada una filtra su taller a mano."""

    def count(model: Any, *where: Any) -> Any:
        return (
            select(func.count())
            .select_from(model)
            .where(model.workshop_id == Workshop.id, *where)
            .scalar_subquery()
        )

    month_start = func.timezone(
        Workshop.timezone,
        func.date_trunc("month", func.timezone(Workshop.timezone, func.now())),
    )
    return {
        Resource.EMPLOYEES_WITH_ACCESS: count(
            Employee, Employee.user_id.is_not(None), Employee.active
        ),
        Resource.EMPLOYEES: count(Employee, Employee.active),
        Resource.CLIENTS: count(Client),
        Resource.VEHICLES: count(Vehicle),
        Resource.ORDERS_PER_MONTH: count(
            WorkOrder, WorkOrder.created_at >= month_start
        ),
    }
