"""Entrar en el portal con un enlace mágico (F4, arquitectura §7.2, decisión 0006).

Se entra desde la página de un taller (`/portal/login/{taller}`), así que todo
ocurre en la transacción de ese taller, con axtton_app y RLS. Ninguna consulta
del portal cruza talleres.

- **La entrada**: el nombre del taller, para su página (sin sesión).
- **Emitir** el enlace de un email en ese taller: si es de un cliente activo, un
  token nuevo, del que se guarda solo el hash.
- **Consumir** un enlace: con el taller de la URL fijado. Un enlace de otro
  taller no se ve (T5), uno usado no vuelve a valer (T6), y lo que sale es un
  `PortalLogin` con el taller y el cliente del enlace guardado, nunca de la
  petición (T10).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import workshop_transaction
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.core.tokens import hash_token, new_token
from app.domain.emails import EmailContent, portal_access_email
from app.domain.portal import LINK_LIFETIME, PortalLogin, access_link
from app.models import Client, Workshop
from app.repositories import clients as client_repo
from app.repositories import portal_links as link_repo
from app.repositories import vehicles as vehicle_repo


class PortalLinkInvalidError(AppError):
    """El enlace no sirve: no existe, es de otro taller, ya se usó, caducó o su
    cliente ya no tiene acceso. Una sola respuesta para todo: distinguirlas diría
    a quien prueba enlaces cuáles existieron."""

    status_code = 400

    def __init__(self) -> None:
        super().__init__("portal_link_invalid")


def _active(workshop: Workshop | None) -> bool:
    # Un taller desactivado corta el portal de sus clientes (RF-113).
    return workshop is not None and workshop.status == "active"


def _has_access(client: Client | None) -> bool:
    """Un cliente entra en el portal si no está archivado y tiene email.

    Anonimizado implica archivado y sin email (CHECK ck_clients_anonymized_empty),
    así que tampoco entra.
    """
    return client is not None and client.archived_at is None and bool(client.email)


class PortalSessionEndedError(AppError):
    """La sesión ya no vale y no volverá a valer: caducó (30 días) o la cerradura
    del cliente cambió. Un 401: el navegador lleva a la entrada del taller."""

    status_code = 401

    def __init__(self) -> None:
        super().__init__("portal_session_ended")


@dataclass(frozen=True)
class PortalEntry:
    """Lo que enseña la página de entrada de un taller, sin sesión."""

    workshop_name: str


async def entry(workshop_id: UUID) -> PortalEntry:
    """El taller de una página de entrada, si existe y está activo.

    Su nombre no es un secreto: es el del propio taller, que da la dirección.
    Lo que nunca dice es quién es cliente suyo.
    """
    async with workshop_transaction([workshop_id]) as session:
        workshop = await session.get(Workshop, workshop_id)
        if workshop is None or not _active(workshop):
            raise NotFoundError("workshop_not_found")
        return PortalEntry(workshop_name=workshop.name)


async def _issue(
    session: AsyncSession, workshop_id: UUID, email: str, app_url: str
) -> EmailContent | None:
    workshop = await session.get(Workshop, workshop_id)
    if workshop is None or not _active(workshop):
        return None
    # El cliente, bloqueado en compartido. Sin el bloqueo, un cambio de email a
    # la vez revocaría los enlaces pendientes sin ver este, que aún no está
    # confirmado, y el enlace quedaría vivo para el email anterior. Con él, el
    # cambio espera a que este se confirme y lo revoca también.
    client = await client_repo.get_by_email_locked(session, email)
    if client is None or not _has_access(client):
        return None
    token = new_token()
    expires_at = await vehicle_repo.db_now(session) + LINK_LIFETIME
    await link_repo.add(session, workshop_id, client.id, hash_token(token), expires_at)
    return portal_access_email(
        workshop_name=workshop.name, link=access_link(app_url, workshop_id, token)
    )


async def issue_link(
    workshop_id: UUID, email: str, *, app_url: str
) -> EmailContent | None:
    """Emite el enlace de ese email en ese taller y devuelve el email que lo
    lleva, o None si no es de un cliente activo de un taller activo.

    Confirma antes de devolver: el email sale después, nunca con un enlace que no
    llegó a guardarse. El email llega ya normalizado, como se guarda.
    """
    async with workshop_transaction([workshop_id]) as session:
        return await _issue(session, workshop_id, email, app_url)


async def consume(workshop_id: UUID, token: str) -> PortalLogin:
    """Cierra el enlace y dice quién entra. Confirma antes de devolver: la sesión
    se crea después, con un enlace que ya no vale para nadie más."""
    async with workshop_transaction([workshop_id]) as session:
        # Comprueba y cierra en una sola sentencia: de dos usos a la vez, el
        # segundo espera al bloqueo de la fila y la encuentra ya usada (T6). Un
        # cambio de email o una anonimización a la vez revoca el enlace con el
        # mismo bloqueo, así que también se ponen en fila con esto.
        client_id = await link_repo.use_if_open(session, hash_token(token))
        if client_id is None:
            raise PortalLinkInvalidError
        workshop = await session.get(Workshop, workshop_id)
        client = await client_repo.get(session, client_id)
        if (
            not _active(workshop)
            or client is None
            or client.email is None
            or not _has_access(client)
        ):
            # Lanzar deshace el cierre: el enlace sigue sin usar. Da igual,
            # porque sin acceso tampoco servirá en otro intento.
            raise PortalLinkInvalidError
        return PortalLogin(
            workshop_id=workshop_id,
            client_id=client.id,
            email=client.email,
            portal_epoch=client.portal_epoch,
        )


@dataclass(frozen=True)
class PortalClient:
    """El cliente de una sesión del portal, tal como está ahora."""

    workshop_name: str
    timezone: str
    client_name: str
    language: str


async def current_client(
    session: AsyncSession,
    workshop_id: UUID,
    client_id: UUID,
    *,
    portal_epoch: int | None,
    expires_at: int | None,
) -> PortalClient:
    """Comprueba en cada petición que la sesión sigue dando acceso (RNF-02).

    La sesión dice de qué taller y de qué cliente es, pero no que sigan activos.
    Dos casos distintos:

    - **Ya no valdrá nunca** (401): pasaron sus 30 días (RF-47), o cambió la
      cerradura del cliente (otro email, o anonimizado). La cerradura la corta al
      instante, sin esperar a que caduque el token de acceso, y también si la
      sesión se creó justo después de cambiarla.
    - **Ahora no hay acceso** (403): un taller desactivado (RF-113) o un cliente
      archivado. Si los reactivan, la misma sesión vuelve a valer.
    """
    if expires_at is None or datetime.now(UTC).timestamp() >= expires_at:
        raise PortalSessionEndedError
    workshop = await session.get(Workshop, workshop_id)
    client = await client_repo.get(session, client_id)
    if client is not None and client.portal_epoch != portal_epoch:
        raise PortalSessionEndedError
    if (
        workshop is None
        or not _active(workshop)
        or client is None
        or not _has_access(client)
    ):
        raise ForbiddenError("portal_access_revoked")
    return PortalClient(
        workshop_name=workshop.name,
        timezone=workshop.timezone,
        client_name=client.name,
        language=client.language,
    )
