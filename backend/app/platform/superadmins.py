"""Superadministradores: invitar a otro desde la aplicación (RF-110).

El primero se crea con el comando del servidor (`app.scripts.create_superadmin`);
los demás, por invitación de uno que ya lo es. Todo es de plataforma: la tabla
`superadmin_invitations` no tiene taller ni RLS y solo la lee este rol.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.tokens import hash_token, new_token
from app.domain.invitations import (
    INVITATION_VALIDITY,
    superadmin_invitation_email,
    superadmin_invitation_path,
)
from app.infra import identity
from app.infra.email import Email, EmailSender
from app.models import AuditEntry, SuperadminInvitation, User
from app.platform.db import platform_transaction


async def invite(*, email: str, invited_by: str, email_sender: EmailSender) -> bool:
    """Crea la invitación y la envía. Devuelve si salió el email.

    Una invitación nueva anula las pendientes del mismo email: solo vale el
    último enlace. El email se envía DESPUÉS del commit, como el alta de talleres.
    """
    email = email.strip().lower()
    token = new_token()
    async with platform_transaction() as session:
        inviter = await session.scalar(
            select(User.id).where(User.supertokens_user_id == invited_by)
        )
        now = datetime.now(UTC)
        await session.execute(
            update(SuperadminInvitation)
            .where(
                func.lower(SuperadminInvitation.email) == email,
                SuperadminInvitation.accepted_at.is_(None),
                SuperadminInvitation.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        invitation = SuperadminInvitation(
            email=email,
            token_hash=hash_token(token),
            expires_at=now + INVITATION_VALIDITY,
            created_by_user_id=inviter,
        )
        session.add(invitation)
        await session.flush()
        # Aquí el email sí va en la auditoría: a quién se invitó a administrar la
        # plataforma es justo lo que hay que poder saber después.
        session.add(
            AuditEntry(
                actor_user_id=inviter,
                action="superadmin_invited",
                target_type="superadmin_invitation",
                target_id=invitation.id,
                details={"email": email},
            )
        )

    if not email_sender.enabled:
        return False
    subject, body = superadmin_invitation_email(
        link=get_settings().app_url + superadmin_invitation_path(token)
    )
    await email_sender.send(Email(to=email, subject=subject, body=body))
    return True


def _usable(invitation: SuperadminInvitation | None) -> SuperadminInvitation:
    # Mismo error para "no existe", "caducada" o "anulada": el enlace no revela más.
    if (
        invitation is None
        or invitation.revoked_at is not None
        or invitation.expires_at <= datetime.now(UTC)
    ):
        raise NotFoundError("invitation_not_found")
    if invitation.accepted_at is not None:
        raise ConflictError("invitation_already_accepted")
    return invitation


async def view(token: str) -> str:
    """El email invitado, para enseñarlo en la página del enlace."""
    async with platform_transaction() as session:
        invitation = await session.scalar(
            select(SuperadminInvitation).where(
                SuperadminInvitation.token_hash == hash_token(token)
            )
        )
        return _usable(invitation).email


async def accept(token: str, password: str) -> None:
    async with platform_transaction() as session:
        # 1. Bloquear la invitación: dos aceptaciones a la vez se ponen en fila.
        invitation = _usable(
            await session.scalar(
                select(SuperadminInvitation)
                .where(SuperadminInvitation.token_hash == hash_token(token))
                .with_for_update()
            )
        )

        # 2. La cuenta de SuperTokens: se crea o, si el email ya tiene una, se
        #    exige su contraseña (demuestra que es suya).
        try:
            supertokens_user_id = await identity.create_or_verify_account(
                invitation.email, password
            )
        except identity.WrongPasswordError:
            raise ForbiddenError("wrong_password") from None

        # 3. Un superadministrador nunca es empleado (arquitectura §2): una
        #    cuenta de personal no se convierte; hace falta otro email.
        user = await session.scalar(
            select(User).where(User.supertokens_user_id == supertokens_user_id)
        )
        if user is not None and user.kind == "staff":
            raise ConflictError("staff_cannot_be_superadmin")
        if user is None:
            user = User(supertokens_user_id=supertokens_user_id, kind="superadmin")
            session.add(user)
            await session.flush()

        invitation.accepted_at = datetime.now(UTC)
        session.add(
            AuditEntry(
                actor_user_id=user.id,
                action="superadmin_created",
                target_type="user",
                target_id=user.id,
                # Quién invitó ya consta en la entrada superadmin_invited.
                details={"email": invitation.email},
            )
        )


@dataclass(frozen=True)
class Superadmin:
    email: str
    created_at: datetime


@dataclass(frozen=True)
class PendingInvitation:
    id: UUID
    email: str
    expires_at: datetime


async def list_superadmins() -> tuple[list[Superadmin], list[PendingInvitation]]:
    async with platform_transaction() as session:
        users = (
            await session.execute(
                select(User.supertokens_user_id, User.created_at)
                .where(User.kind == "superadmin")
                .order_by(User.created_at)
            )
        ).all()
        pending = (
            await session.scalars(
                select(SuperadminInvitation)
                .where(
                    SuperadminInvitation.accepted_at.is_(None),
                    SuperadminInvitation.revoked_at.is_(None),
                    SuperadminInvitation.expires_at > func.clock_timestamp(),
                )
                .order_by(SuperadminInvitation.created_at.desc())
            )
        ).all()
    # El email vive en SuperTokens: uno por superadministrador (son pocos).
    superadmins = [
        Superadmin(await identity.email_of(st_id), created_at)
        for st_id, created_at in users
    ]
    return superadmins, [
        PendingInvitation(i.id, i.email, i.expires_at) for i in pending
    ]
