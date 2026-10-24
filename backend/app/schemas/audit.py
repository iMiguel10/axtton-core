from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEntryRead(BaseModel):
    seq: int
    created_at: datetime
    action: str
    # El empleado (en el taller) o el email (en la plataforma) de quien actuó.
    # Nulo si ya no se puede saber.
    actor: str | None
    target_type: str | None
    target_name: str | None
    # Qué cambió: {"campo": [antes, después]}, o datos de la acción.
    details: dict[str, Any]


class AuditPageRead(BaseModel):
    entries: list[AuditEntryRead]
    # Se pasa como ?before= para pedir las entradas anteriores.
    next_before: int | None
