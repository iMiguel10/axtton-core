"""Ver y aceptar una invitación (RF-04, RF-07).

Quien acepta todavía no tiene sesión: la ruta es pública, y el taller llega en
el propio enlace y se fija para RLS. Un enlace con el taller cambiado busca el
token en otro taller y no lo encuentra.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.tokens import hash_token
from app.infra.identity import WrongPasswordError, create_or_verify_account
from app.models import AuditEntry, Invitation, Workshop
from app.repositories import employees as employee_repo
from app.repositories import invitations as invitation_repo
from app.repositories import users as user_repo


@dataclass(frozen=True)
class InvitationView:
    workshop_name: str
    employee_name: str
    email: str


def _usable(invitation: Invitation | None) -> Invitation:
    # Mismo error para "no existe", "es de otro taller", "caducada" o "anulada":
    # el enlace no revela nada más que "no sirve".
    if (
        invitation is None
        or invitation.revoked_at is not None
        or invitation.expires_at <= datetime.now(UTC)
    ):
        raise NotFoundError("invitation_not_found")
    return invitation


async def view(session: AsyncSession, token: str) -> InvitationView:
    invitation = _usable(
        await invitation_repo.get_by_token_hash(session, hash_token(token))
    )
    if invitation.accepted_at is not None:
        raise ConflictError("invitation_already_accepted")
    workshop = await session.get(Workshop, invitation.workshop_id)
    employee = await employee_repo.get(session, invitation.employee_id)
    assert workshop is not None and employee is not None
    return InvitationView(
        workshop_name=workshop.name, employee_name=employee.name, email=invitation.email
    )


async def accept(
    session: AsyncSession, workshop_id: UUID, token: str, password: str
) -> None:
    # 0. En fila con los demás cambios del personal de este taller: dos
    #    aceptaciones de invitaciones DISTINTAS con un solo hueco libre entrarían
    #    las dos (RF-114). Primero este bloqueo y después el de la fila, en el
    #    mismo orden que invite y remove_access, para no cruzarse.
    await employee_repo.lock_staff(session, workshop_id)
    # 1. Bloquear la invitación: dos aceptaciones de la misma se ponen en fila.
    invitation = _usable(
        await invitation_repo.get_by_token_hash(session, hash_token(token), lock=True)
    )
    if invitation.accepted_at is not None:
        raise ConflictError("invitation_already_accepted")
    workshop = await session.get(Workshop, workshop_id)
    employee = await employee_repo.get(session, invitation.employee_id)
    assert workshop is not None and employee is not None
    if workshop.status != "active":
        raise NotFoundError("invitation_not_found")
    if employee.user_id is not None:
        raise ConflictError("employee_already_has_access")

    # 2. Comprobar el límite ANTES de tocar SuperTokens: si no hay hueco, no se
    #    crea ninguna cuenta.
    if (
        await employee_repo.count_with_access(session, workshop_id)
        >= workshop.max_employees_with_access
    ):
        raise ConflictError("employee_limit_reached")

    # 3. La cuenta de SuperTokens: se crea o, si ya existe, se exige su
    #    contraseña. Es lo único que no está en nuestra transacción; si algo falla
    #    después, la cuenta queda sin fila en users (no puede iniciar sesión) y
    #    reintentar la aceptación la recupera.
    try:
        supertokens_user_id = await create_or_verify_account(invitation.email, password)
    except WrongPasswordError:
        raise ForbiddenError("wrong_password") from None

    # 4. Nuestra cuenta: la existente (si la persona ya trabaja en otro taller,
    #    RF-07) o una nueva.
    user = await user_repo.get_by_supertokens_id(session, supertokens_user_id)
    if user is None:
        user = await user_repo.create_staff(session, supertokens_user_id)
    elif user.kind != "staff":
        # Un superadministrador nunca es empleado: usa otra cuenta (arquitectura §2).
        raise ConflictError("superadmin_cannot_be_employee")

    # 5. Ligar la ficha, cerrar la invitación y dejar constancia.
    employee.user_id = user.id
    invitation.accepted_at = datetime.now(UTC)
    session.add(
        AuditEntry(
            workshop_id=workshop_id,
            actor_user_id=user.id,
            action="invitation_accepted",
            target_type="employee",
            target_id=employee.id,
        )
    )
    # Si este usuario ya era empleado de este taller con otra ficha, la
    # restricción UNIQUE (workshop_id, user_id) lo rechaza al confirmar.
    await session.flush()
