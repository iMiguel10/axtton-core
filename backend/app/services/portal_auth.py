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

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import workshop_transaction
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.core.tokens import hash_token, new_token
from app.domain.emails import portal_access_email
from app.domain.portal import (
    DEMO_CLIENT_DOMAIN,
    DEMO_CLIENTS_SHOWN,
    LINK_JOB_KEEP,
    LINK_JOB_TIMEOUT,
    LINK_LIFETIME,
    LINK_RETENTION,
    LINK_RETRY_DELAY,
    LINK_SEND_ATTEMPTS,
    PortalLogin,
    access_link,
)
from app.infra.email import (
    EmailDeliveryUnknownError,
    EmailNotSentError,
    EmailSender,
    compose,
)
from app.infra.queue import JobQueue, QueueUnavailableError
from app.models import Client, Workshop
from app.repositories import clients as client_repo
from app.repositories import portal_links as link_repo
from app.repositories import settings as settings_repo
from app.repositories import vehicles as vehicle_repo

logger = logging.getLogger(__name__)


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
    has_logo: bool


@dataclass(frozen=True)
class EntryLogo:
    content: bytes
    media_type: str


async def entry(workshop_id: UUID) -> PortalEntry:
    """El taller de una página de entrada, si existe y está activo.

    Su nombre no es un secreto: es el del propio taller, que da la dirección.
    Lo que nunca dice es quién es cliente suyo.
    """
    async with workshop_transaction([workshop_id]) as session:
        workshop = await session.get(Workshop, workshop_id)
        if workshop is None or not _active(workshop):
            raise NotFoundError("workshop_not_found")
        return PortalEntry(
            workshop_name=workshop.name,
            has_logo=await settings_repo.has_logo(session, workshop_id),
        )


async def entry_logo(workshop_id: UUID) -> EntryLogo:
    """El logotipo de la entrada (decisión 0007, que amplía la 0005): el PNG que
    el servidor volvió a dibujar al subirlo, nunca lo que se subió. Es la marca
    del taller, pública como su nombre."""
    async with workshop_transaction([workshop_id]) as session:
        workshop = await session.get(Workshop, workshop_id)
        if workshop is None or not _active(workshop):
            raise NotFoundError("workshop_not_found")
        logo = await settings_repo.get_logo(session, workshop_id)
        if logo is None:
            raise NotFoundError("logo_not_found")
        return EntryLogo(logo.content, logo.media_type)


@dataclass(frozen=True)
class _Issued:
    workshop: Workshop
    # El token no se guarda: solo su hash.
    token: str
    link_id: UUID


async def _issue(
    session: AsyncSession, workshop_id: UUID, email: str
) -> _Issued | None:
    """Guarda un enlace nuevo y devuelve su taller, su token y su id."""
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
    link_id = await link_repo.add(
        session, workshop_id, client.id, hash_token(token), expires_at
    )
    return _Issued(workshop, token, link_id)


async def request_link(queue: JobQueue, workshop_id: UUID, email: str) -> None:
    """Deja el envío del enlace al worker (F5 paso 8) sin mirar nada más: ni si
    el email es de un cliente ni si el taller existe. Así la respuesta no depende
    de eso, ni en lo que dice ni en lo que tarda (RF-41).

    El trabajo lleva el email, que hace falta para enviarlo, y nunca el token: el
    enlace se emite al enviarlo (arquitectura §8). Si la cola no responde, queda
    en el registro (sin el email) y quien lo pidió puede volver a pedirlo.
    """
    try:
        await queue.enqueue(
            "send_portal_link",
            timeout_seconds=int(LINK_JOB_TIMEOUT.total_seconds()),
            max_attempts=LINK_SEND_ATTEMPTS,
            retry_delay_seconds=LINK_RETRY_DELAY.total_seconds(),
            keep_seconds=int(LINK_JOB_KEEP.total_seconds()),
            workshop_id=str(workshop_id),
            email=email,
        )
    except QueueUnavailableError:
        logger.exception("No se pudo encolar el acceso al portal")


class LinkSendOutcome(StrEnum):
    SENT = "sent"
    # No es un cliente con acceso de un taller activo: no se envía nada.
    NO_ACCESS = "no_access"
    # El worker no tiene SMTP.
    EMAIL_DISABLED = "email_disabled"
    # Se cortó con el mensaje en vuelo: pudo llegar, y no se reintenta.
    DELIVERY_UNKNOWN = "delivery_unknown"


class LinkNotSentError(Exception):
    """El correo no salió y se puede reintentar: SAQ lo vuelve a intentar con
    otro enlace. Sin el texto del servidor, que podría llevar el email y que SAQ
    guardaría en Valkey con el trabajo."""

    def __init__(self, smtp_code: int | None) -> None:
        super().__init__(f"portal link not sent (smtp code {smtp_code})")
        self.smtp_code = smtp_code


async def send_link(
    workshop_id: UUID, email: str, sender: EmailSender
) -> LinkSendOutcome:
    """Emite el enlace de ese email en ese taller y lo envía (en el worker).

    Emitirlo se confirma antes de enviar: el correo nunca lleva un enlace que no
    llegó a guardarse. Si no salió, ese enlace se revoca y se lanza
    `LinkNotSentError` para que el siguiente intento emita otro; si no se sabe,
    no se reintenta (arquitectura §8). El email llega ya normalizado.
    """
    if not sender.enabled:
        return LinkSendOutcome.EMAIL_DISABLED
    async with workshop_transaction([workshop_id]) as session:
        issued = await _issue(session, workshop_id, email)
    if issued is None:
        return LinkSendOutcome.NO_ACCESS
    content = portal_access_email(
        workshop_name=issued.workshop.name,
        link=access_link(get_settings().app_url, workshop_id, issued.token),
    )
    try:
        await sender.send(compose(email, content))
    except EmailNotSentError as exc:
        async with workshop_transaction([workshop_id]) as session:
            await link_repo.revoke_if_open(session, issued.link_id)
        raise LinkNotSentError(exc.smtp_code) from None
    except EmailDeliveryUnknownError:
        logger.warning("El acceso al portal pudo no llegar; no se reintenta")
        return LinkSendOutcome.DELIVERY_UNKNOWN
    return LinkSendOutcome.SENT


# --- La entrada de la demo (F4 paso 8) -----------------------------------------


@dataclass(frozen=True)
class DemoClient:
    name: str
    email: str


def _demo_entry_enabled() -> None:
    # Apagada, las dos rutas no existen: un 404, como cualquier ruta que no hay.
    if not get_settings().demo_portal_entry:
        raise NotFoundError("not_found")


async def demo_clients(workshop_id: UUID) -> list[DemoClient]:
    """Los clientes de la demo de un taller, para entrar sin correo. Solo los del
    dominio de la demo: los que pone el script, nunca uno de verdad."""
    _demo_entry_enabled()
    async with workshop_transaction([workshop_id]) as session:
        workshop = await session.get(Workshop, workshop_id)
        if not _active(workshop):
            raise NotFoundError("workshop_not_found")
        clients = await client_repo.with_email_domain(
            session, DEMO_CLIENT_DOMAIN, DEMO_CLIENTS_SHOWN
        )
        return [DemoClient(c.name, c.email) for c in clients if c.email]


async def demo_login(workshop_id: UUID, email: str) -> PortalLogin:
    """Entrar como un cliente de la demo, que no tiene correo. Emite un enlace de
    verdad y lo consume en el acto: la sesión nace por el mismo camino que con el
    correo (`consume` y después `create_client_session`, T10), y caduca, se
    revoca y se cierra igual. El email llega normalizado."""
    _demo_entry_enabled()
    if not email.endswith(DEMO_CLIENT_DOMAIN):
        raise NotFoundError("demo_client_not_found")
    async with workshop_transaction([workshop_id]) as session:
        issued = await _issue(session, workshop_id, email)
    if issued is None:
        raise NotFoundError("demo_client_not_found")
    return await consume(workshop_id, issued.token)


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


async def purge_expired_links(workshop_id: UUID) -> int:
    """Borra los enlaces de un taller caducados hace más de LINK_RETENTION (F5
    paso 1). Lo llama el worker taller a taller, con ese taller fijado: el
    planificador solo dice cuáles tienen algo que borrar (arquitectura §4)."""
    async with workshop_transaction([workshop_id]) as session:
        return await link_repo.delete_expired(session, LINK_RETENTION)
