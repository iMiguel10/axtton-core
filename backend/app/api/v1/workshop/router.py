from fastapi import APIRouter

from app.api.v1.workshop.deps import WorkshopSession
from app.repositories.clients import list_client_names

router = APIRouter(prefix="/api/v1/workshop", tags=["workshop"])


@router.get("/clients")
async def list_clients(session: WorkshopSession) -> list[str]:
    """F0: los nombres de los clientes del taller de la cabecera X-Workshop-Id."""
    return await list_client_names(session)
