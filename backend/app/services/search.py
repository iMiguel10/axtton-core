"""La búsqueda única del mostrador (RF-14).

Lo escrito se busca a la vez como matrícula, como nombre y como teléfono, y la
respuesta trae lo necesario para seguir sin otra búsqueda: cada vehículo con su
titular, y cada cliente con sus vehículos.
"""

from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.search import MAX_RESULTS, terms
from app.models import Client, Vehicle
from app.repositories import search as search_repo


@dataclass(frozen=True)
class ClientHit:
    client: Client
    vehicles: list[Vehicle]


@dataclass(frozen=True)
class SearchResult:
    vehicles: list[tuple[Vehicle, Client | None]]
    clients: list[ClientHit]


async def search(session: AsyncSession, query: str) -> SearchResult:
    found = terms(query)
    if found.empty:
        return SearchResult([], [])
    vehicles = (
        await search_repo.vehicles_by_plate(session, found.plate, MAX_RESULTS)
        if found.plate
        else []
    )
    clients = await search_repo.clients_by_name_or_phone(
        session, found.text, found.digits, MAX_RESULTS
    )
    owned: dict[UUID, list[Vehicle]] = defaultdict(list)
    for client_id, vehicle in await search_repo.current_vehicles_of(
        session, [c.id for c in clients]
    ):
        owned[client_id].append(vehicle)
    return SearchResult(
        vehicles=vehicles,
        clients=[ClientHit(client, owned[client.id]) for client in clients],
    )
