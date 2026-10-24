"""Administración de talleres por el superadministrador (RF-110 a RF-114).

Usa el rol de plataforma porque trabaja con varios talleres a la vez. Nunca
devuelve datos operativos de un taller (clientes, órdenes, empleados uno a uno):
solo datos de cuenta y recuentos (RNF-08).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.tokens import hash_token, new_token
from app.infra.email import Email, EmailSender
from app.models import AuditEntry, Employee, Invitation, User, Workshop
from app.platform.db import platform_transaction

INVITATION_VALIDITY = timedelta(days=7)  # especificación §10


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
        # Taller único (RF-111): se crea una vez y nunca más.
        if get_settings().installation_mode == "single" and await session.scalar(
            select(func.count()).select_from(Workshop)
        ):
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
        link = f"{get_settings().app_url}/invitations/{workshop_id}/{token}"
        await email_sender.send(
            Email(
                to=admin_email,
                subject=f"Te han dado acceso a {name} en AXTTON CORE",
                body=(
                    f"Hola, {admin_name}:\n\n"
                    f"Se ha dado de alta el taller «{name}» y eres su administrador.\n"
                    f"Para activar tu acceso, abre este enlace (caduca en 7 días):\n\n"
                    f"{link}\n\n"
                    "Si no esperabas este mensaje, ignóralo."
                ),
            )
        )
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


async def list_workshops() -> list[WorkshopSummary]:
    """Talleres con datos de cuenta y uso respecto a los límites (RF-114)."""
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
        rows = await session.execute(
            select(
                Workshop.id,
                Workshop.name,
                Workshop.status,
                Workshop.created_at,
                Workshop.max_employees_with_access,
                with_access,
                pending,
            ).order_by(Workshop.created_at)
        )
        return [WorkshopSummary(*row) for row in rows]


async def update_workshop(
    workshop_id: UUID,
    *,
    status: str | None,
    max_employees_with_access: int | None,
    updated_by: str,
) -> None:
    """Desactivar o reactivar (RF-113) y ajustar el límite de acceso (RF-114).

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
        if (
            max_employees_with_access is not None
            and max_employees_with_access != workshop.max_employees_with_access
        ):
            changes["max_employees_with_access"] = [
                workshop.max_employees_with_access,
                max_employees_with_access,
            ]
            workshop.max_employees_with_access = max_employees_with_access
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
