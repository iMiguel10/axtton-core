"""El acceso al portal (F5 paso 8, arquitectura §8): el enlace mágico se envía
desde el worker, con reintentos, en vez de desde la API después de responder.
"""

from uuid import UUID

from app.jobs.context import WorkerContext
from app.services import portal_auth as portal_auth_service


async def send_portal_link(ctx: WorkerContext, *, workshop_id: str, email: str) -> str:
    """Emite el enlace y lo envía. Lo que devuelve (cómo acabó, sin el email)
    es lo que SAQ guarda como resultado."""
    outcome = await portal_auth_service.send_link(
        UUID(workshop_id), email, ctx["email_sender"]
    )
    return outcome.value
