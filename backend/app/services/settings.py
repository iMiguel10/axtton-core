"""Configuración del taller activo por su administrador (RF-02).

Los datos legales y los ajustes se guardan en `workshops`, sobre las únicas
columnas que `axtton_app` puede escribir (migración 0012settings); el
logotipo, en `workshop_logos`; las tarifas, en `labor_rates`. Todo se audita
(RNF-16): son los datos que salen en un presupuesto con valor legal (RF-37) y
los precios con los que se calcula.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.domain.clients import normalize_email, normalize_tax_id
from app.domain.settings import MAX_ACTIVE_LABOR_RATES
from app.infra.images import InvalidImageError, normalize_logo
from app.models import AuditEntry, LaborRate, Workshop, WorkshopLogo
from app.repositories import settings as settings_repo
from app.services.integrity import flush_or_conflict

# Lo que el administrador cambia con PUT /workshop/settings. Tiene que coincidir
# con las columnas que le concede la migración 0012settings: una que no esté
# allí daría "permission denied".
EDITABLE = (
    "name",
    "legal_name",
    "tax_id",
    "address",
    "phone",
    "reply_to_email",
    "industrial_registry_number",
    "default_vat_bp",
    "quote_validity_business_days",
    "mechanics_see_sale_prices",
)
OPTIONAL_TEXT = (
    "legal_name",
    "tax_id",
    "address",
    "phone",
    "reply_to_email",
    "industrial_registry_number",
)

RATE_UNIQUE = {
    "uq_labor_rates_workshop_id_name": "labor_rate_name_taken",
    "uq_labor_rates_workshop_id_default": "labor_rate_default_conflict",
}


def _audit(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    action: str,
    target_type: str,
    target_id: UUID,
    details: dict[str, Any],
) -> None:
    session.add(
        AuditEntry(
            workshop_id=workshop_id,
            actor_user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
        )
    )


# --- Datos del taller --------------------------------------------------------


async def get_workshop(session: AsyncSession, workshop_id: UUID) -> Workshop:
    workshop = await settings_repo.get_workshop(session, workshop_id)
    if workshop is None:
        raise NotFoundError("workshop_not_found")
    return workshop


async def has_logo(session: AsyncSession, workshop_id: UUID) -> bool:
    return await settings_repo.has_logo(session, workshop_id)


def _normalized(changes: dict[str, Any]) -> dict[str, Any]:
    result = dict(changes)
    # Un campo opcional vacío es "no lo sé", no un texto: se guarda nulo.
    for field in OPTIONAL_TEXT:
        if field in result and not result[field]:
            result[field] = None
    if result.get("tax_id") is not None:
        result["tax_id"] = normalize_tax_id(result["tax_id"]) or None
    if result.get("reply_to_email") is not None:
        result["reply_to_email"] = normalize_email(result["reply_to_email"])
    return result


async def update_workshop(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    *,
    expected_version: int,
    changes: dict[str, Any],
) -> None:
    """Bloqueo optimista (RNF-15): si otro administrador guardó antes, 409. Se
    audita solo lo que cambió, con el valor anterior y el nuevo."""
    workshop = await get_workshop(session, workshop_id)
    if workshop.version != expected_version:
        raise ConflictError("modified_by_someone_else")
    values = _normalized(changes)
    changed: dict[str, Any] = {}
    for field in EDITABLE:
        if field in values and getattr(workshop, field) != values[field]:
            changed[field] = [getattr(workshop, field), values[field]]
            setattr(workshop, field, values[field])
    if not changed:
        return
    _audit(
        session,
        workshop_id,
        user_id,
        "workshop_settings_updated",
        "workshop",
        workshop_id,
        changed,
    )
    await session.flush()


# --- Logotipo (decisión 0005) -------------------------------------------------


async def get_logo(session: AsyncSession, workshop_id: UUID) -> WorkshopLogo:
    logo = await settings_repo.get_logo(session, workshop_id)
    if logo is None:
        raise NotFoundError("logo_not_found")
    return logo


async def set_logo(
    session: AsyncSession, workshop_id: UUID, user_id: UUID, data: bytes
) -> None:
    """Se guarda la imagen re-dibujada por el servidor, nunca la subida."""
    try:
        png = await normalize_logo(data)
    except InvalidImageError as error:
        raise ValidationFailedError("invalid_logo") from error
    logo = await settings_repo.get_logo(session, workshop_id)
    if logo is None:
        session.add(
            WorkshopLogo(
                workshop_id=workshop_id,
                content=png.content,
                width=png.width,
                height=png.height,
            )
        )
    else:
        logo.content = png.content
        logo.width = png.width
        logo.height = png.height
    _audit(
        session,
        workshop_id,
        user_id,
        "workshop_logo_updated",
        "workshop",
        workshop_id,
        {},
    )
    await session.flush()


async def remove_logo(session: AsyncSession, workshop_id: UUID, user_id: UUID) -> None:
    logo = await settings_repo.get_logo(session, workshop_id)
    if logo is None:
        return
    await session.delete(logo)
    _audit(
        session,
        workshop_id,
        user_id,
        "workshop_logo_removed",
        "workshop",
        workshop_id,
        {},
    )
    await session.flush()


# --- Tarifas de mano de obra (RF-02) -----------------------------------------


async def list_labor_rates(session: AsyncSession, *, archived: bool) -> list[LaborRate]:
    return await settings_repo.list_labor_rates(session, archived=archived)


async def _get_rate(session: AsyncSession, rate_id: UUID) -> LaborRate:
    rate = await settings_repo.get_labor_rate(session, rate_id)
    if rate is None:
        raise NotFoundError("labor_rate_not_found")
    return rate


def _check_version(rate: LaborRate, expected: int) -> None:
    if rate.version != expected:
        raise ConflictError("modified_by_someone_else")


async def _make_default(session: AsyncSession, rate: LaborRate) -> None:
    """La que se marca pasa a ser la única por defecto. Va siempre con
    `lock_labor_rates` cogido: quitar la marca y ponerla tienen que ser un solo
    paso para cualquier otro que lo intente a la vez."""
    await settings_repo.clear_default(session, except_id=rate.id)
    rate.is_default = True


async def create_labor_rate(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    *,
    name: str,
    hourly_price_cents: int,
    is_default: bool,
) -> UUID:
    await settings_repo.lock_labor_rates(session, workshop_id)
    active = await settings_repo.active_labor_rates(session)
    if active >= MAX_ACTIVE_LABOR_RATES:
        raise ConflictError("labor_rate_limit_reached")
    if await settings_repo.name_taken(session, name):
        raise ConflictError("labor_rate_name_taken")
    # La primera es la de por defecto aunque no se pida: un taller con tarifas
    # siempre tiene una que proponer en una línea nueva (RF-02).
    default = is_default or active == 0
    if default:
        await settings_repo.clear_default(session)
    rate = LaborRate(
        workshop_id=workshop_id,
        name=name,
        hourly_price_cents=hourly_price_cents,
        is_default=default,
    )
    session.add(rate)
    await flush_or_conflict(session, RATE_UNIQUE)
    _audit(
        session,
        workshop_id,
        user_id,
        "labor_rate_created",
        "labor_rate",
        rate.id,
        {"labor_rate": name, "hourly_price_cents": hourly_price_cents},
    )
    await flush_or_conflict(session, RATE_UNIQUE)
    return rate.id


async def update_labor_rate(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    rate_id: UUID,
    *,
    expected_version: int,
    changes: dict[str, Any],
) -> None:
    """Cambiar el precio no toca ningún presupuesto: sus líneas lo copiaron."""
    await settings_repo.lock_labor_rates(session, workshop_id)
    rate = await _get_rate(session, rate_id)
    _check_version(rate, expected_version)
    if rate.archived_at is not None:
        raise ConflictError("labor_rate_archived")
    details: dict[str, Any] = {}
    name = changes.get("name")
    if name is not None and name != rate.name:
        if await settings_repo.name_taken(session, name, except_id=rate.id):
            raise ConflictError("labor_rate_name_taken")
        details["labor_rate"] = [rate.name, name]
        rate.name = name
    price = changes.get("hourly_price_cents")
    if price is not None and price != rate.hourly_price_cents:
        details["hourly_price_cents"] = [rate.hourly_price_cents, price]
        rate.hourly_price_cents = price
    if changes.get("is_default") is True and not rate.is_default:
        details["is_default"] = [False, True]
        await _make_default(session, rate)
    # Quitar la marca sin dar otra dejaría al taller sin tarifa por defecto: se
    # cambia marcando otra.
    if changes.get("is_default") is False and rate.is_default:
        raise ConflictError("labor_rate_default_required")
    if not details:
        return
    details.setdefault("labor_rate", rate.name)
    _audit(
        session,
        workshop_id,
        user_id,
        "labor_rate_updated",
        "labor_rate",
        rate.id,
        details,
    )
    await flush_or_conflict(session, RATE_UNIQUE)


async def set_labor_rate_archived(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    rate_id: UUID,
    *,
    expected_version: int,
    archived: bool,
) -> None:
    await settings_repo.lock_labor_rates(session, workshop_id)
    rate = await _get_rate(session, rate_id)
    _check_version(rate, expected_version)
    if (rate.archived_at is not None) == archived:
        return
    if archived and rate.is_default:
        # Con otras vigentes, antes se marca otra como de por defecto. Si es la
        # única, se puede archivar: el taller se queda sin tarifas.
        if await settings_repo.active_labor_rates(session) > 1:
            raise ConflictError("labor_rate_default_required")
        rate.is_default = False
    if not archived:
        if await settings_repo.active_labor_rates(session) >= MAX_ACTIVE_LABOR_RATES:
            raise ConflictError("labor_rate_limit_reached")
        if await settings_repo.name_taken(session, rate.name, except_id=rate.id):
            raise ConflictError("labor_rate_name_taken")
    rate.archived_at = datetime.now(UTC) if archived else None
    _audit(
        session,
        workshop_id,
        user_id,
        "labor_rate_archived" if archived else "labor_rate_unarchived",
        "labor_rate",
        rate.id,
        {"labor_rate": rate.name},
    )
    await flush_or_conflict(session, RATE_UNIQUE)
    # Si se desarchiva y no hay ninguna por defecto (todas estaban archivadas
    # menos ella), pasa a serlo.
    if not archived and await settings_repo.active_labor_rates(session) == 1:
        await _make_default(session, rate)
        await flush_or_conflict(session, RATE_UNIQUE)
