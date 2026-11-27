"""El catálogo de piezas del taller activo (F7 paso 1, RF-90).

Todo bajo RLS: una pieza de otro taller no existe (404). Una pieza no se borra:
se archiva y deja de salir al elegir. Los precios son "fijar precios del
catálogo" (especificación §3): solo el administrador, y su alta y cada cambio de
precio o de IVA quedan en la auditoría (RNF-16), como las tarifas.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.domain.inventory import stock_alert
from app.domain.limits import Resource
from app.models import AuditEntry, Part
from app.repositories import parts as part_repo
from app.repositories import settings as settings_repo
from app.services import limits as limit_service
from app.services import settings as settings_service
from app.services.integrity import flush_or_conflict

# Dos altas a la vez con la misma referencia: el índice para a la segunda.
UNIQUE = {"uq_parts_workshop_id_reference": "part_reference_taken"}

# Lo que cambia PATCH. Archivar tiene sus propias operaciones.
EDITABLE = (
    "reference",
    "description",
    "brand",
    "cost_price_cents",
    "sale_price_cents",
    "vat_bp",
    "part_condition",
    "warranty_months",
    "tracks_stock",
    "min_stock",
)
OPTIONAL_TEXT = ("brand",)
# Lo que se audita (RNF-16: cambios de precios): con el valor anterior y el nuevo.
PRICES = ("cost_price_cents", "sale_price_cents", "vat_bp")


@dataclass(frozen=True)
class PartView:
    id: UUID
    reference: str
    description: str
    brand: str | None
    cost_price_cents: int | None
    sale_price_cents: int | None
    vat_bp: int
    part_condition: str
    warranty_months: int | None
    tracks_stock: bool
    min_stock: Decimal | None
    # La suma de sus movimientos (invariante 9); nulo si no se cuenta.
    stock: Decimal | None
    # En negativo (RF-94) o por debajo del mínimo (RF-95).
    stock_alert: str | None
    archived_at: datetime | None
    created_at: datetime
    version: int


@dataclass(frozen=True)
class Visibility:
    """Lo que puede ver quien mira (especificación §3)."""

    show_costs: bool
    prices_hidden: bool


async def visibility(
    session: AsyncSession, workshop_id: UUID, role: str, *, show_costs: bool
) -> Visibility:
    return Visibility(
        show_costs=show_costs,
        prices_hidden=await settings_service.prices_hidden(session, workshop_id, role),
    )


def _view(part: Part, stock: Decimal, seen: Visibility) -> PartView:
    counted = part.tracks_stock
    alert = stock_alert(stock, part.min_stock) if counted else None
    return PartView(
        id=part.id,
        reference=part.reference,
        description=part.description,
        brand=part.brand,
        cost_price_cents=part.cost_price_cents if seen.show_costs else None,
        sale_price_cents=None if seen.prices_hidden else part.sale_price_cents,
        vat_bp=part.vat_bp,
        part_condition=part.part_condition,
        warranty_months=part.warranty_months,
        tracks_stock=part.tracks_stock,
        min_stock=part.min_stock,
        stock=stock if counted else None,
        stock_alert=alert.value if alert else None,
        archived_at=part.archived_at,
        created_at=part.created_at,
        version=part.version,
    )


def _normalized(changes: dict[str, Any]) -> dict[str, Any]:
    result = dict(changes)
    # Una marca vacía es "no la sé", no un texto: se guarda nula.
    for field in OPTIONAL_TEXT:
        if field in result and not result[field]:
            result[field] = None
    return result


async def _get(session: AsyncSession, part_id: UUID) -> Part:
    part = await part_repo.get(session, part_id)
    if part is None:
        raise NotFoundError("part_not_found")
    return part


def _check_version(part: Part, expected: int) -> None:
    """Bloqueo optimista a nivel HTTP (RNF-15)."""
    if part.version != expected:
        raise ConflictError("modified_by_someone_else")


def _audit(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    action: str,
    part: Part,
    details: dict[str, Any],
) -> None:
    session.add(
        AuditEntry(
            workshop_id=workshop_id,
            actor_user_id=user_id,
            action=action,
            target_type="part",
            target_id=part.id,
            details=details,
        )
    )


async def list_parts(
    session: AsyncSession,
    workshop_id: UUID,
    role: str,
    *,
    show_costs: bool,
    query: str | None,
    archived: bool,
    alert: bool,
    limit: int,
    offset: int,
) -> tuple[list[PartView], bool]:
    """Las piezas con su stock, y si sus precios de venta van ocultos para quien
    mira. Con `alert`, solo las que tienen una incidencia de stock."""
    seen = await visibility(session, workshop_id, role, show_costs=show_costs)
    rows = await part_repo.list_page(
        session,
        query=query.strip() if query else None,
        archived=archived,
        alert=alert,
        limit=limit,
        offset=offset,
    )
    return [_view(part, stock, seen) for part, stock in rows], seen.prices_hidden


async def get_part(
    session: AsyncSession,
    workshop_id: UUID,
    role: str,
    part_id: UUID,
    *,
    show_costs: bool,
) -> PartView:
    seen = await visibility(session, workshop_id, role, show_costs=show_costs)
    found = await part_repo.get_with_stock(session, part_id)
    if found is None:
        raise NotFoundError("part_not_found")
    return _view(*found, seen)


async def create_part(
    session: AsyncSession, workshop_id: UUID, user_id: UUID, fields: dict[str, Any]
) -> UUID:
    # Primero el límite (§10): es el primer bloqueo de toda alta.
    await limit_service.ensure_room(session, workshop_id, Resource.PARTS)
    values = _normalized(fields)
    if values.get("vat_bp") is None:
        workshop = await settings_repo.get_workshop(session, workshop_id)
        assert workshop is not None
        values["vat_bp"] = workshop.default_vat_bp
    if await part_repo.reference_taken(session, values["reference"]):
        raise ConflictError("part_reference_taken")
    part = Part(workshop_id=workshop_id, **values)
    session.add(part)
    await flush_or_conflict(session, UNIQUE)
    _audit(
        session,
        workshop_id,
        user_id,
        "part_created",
        part,
        {"part": part.reference} | {field: getattr(part, field) for field in PRICES},
    )
    await session.flush()
    return part.id


async def update_part(
    session: AsyncSession,
    workshop_id: UUID,
    user_id: UUID,
    part_id: UUID,
    *,
    expected_version: int,
    changes: dict[str, Any],
) -> None:
    """Cambiar el precio no toca ningún presupuesto: sus líneas lo copiaron
    (RF-38). Una pieza archivada no se edita: antes se desarchiva."""
    part = await _get(session, part_id)
    _check_version(part, expected_version)
    if part.archived_at is not None:
        raise ConflictError("part_archived")
    values = _normalized(changes)
    reference = values.get("reference")
    if (
        reference is not None
        and reference.lower() != part.reference.lower()
        and await part_repo.reference_taken(session, reference, except_id=part.id)
    ):
        raise ConflictError("part_reference_taken")
    # Sin control de stock no hay mínimo (RF-95): dejar de contar lo borra.
    if values.get("tracks_stock") is False:
        values["min_stock"] = None
    elif values.get("min_stock") is not None and not values.get(
        "tracks_stock", part.tracks_stock
    ):
        raise ConflictError("part_min_stock_without_stock")
    details: dict[str, Any] = {}
    for field in PRICES:
        if field in values and values[field] != getattr(part, field):
            details[field] = [getattr(part, field), values[field]]
    for field in EDITABLE:
        if field in values:
            setattr(part, field, values[field])
    if details:
        _audit(
            session,
            workshop_id,
            user_id,
            "part_prices_changed",
            part,
            {"part": part.reference} | details,
        )
    await flush_or_conflict(session, UNIQUE)


async def set_archived(
    session: AsyncSession, part_id: UUID, *, expected_version: int, archived: bool
) -> None:
    """Archivar la saca de los listados y de lo que se puede elegir, sin borrar
    nada: lo que ya la usó la sigue nombrando."""
    part = await _get(session, part_id)
    _check_version(part, expected_version)
    if (part.archived_at is not None) == archived:
        return
    part.archived_at = datetime.now(UTC) if archived else None
    await session.flush()
