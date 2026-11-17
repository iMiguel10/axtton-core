"""Los avisos de una orden como los ve el taller (F5 paso 7, RF-69)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.notifications import (
    FailureReason,
    NotificationKind,
    NotificationStatus,
)


class NotificationRead(BaseModel):
    id: UUID
    kind: NotificationKind
    # La versión del presupuesto de la que avisa; sin presupuesto, `None`.
    quote_version_no: int | None
    status: NotificationStatus
    # Por qué no salió, como código: la interfaz lo explica (RNF-40: el texto
    # del servidor no se guarda).
    failure_reason: FailureReason | None
    smtp_code: int | None
    attempts: int
    created_at: datetime
    sent_at: datetime | None
    # Cuándo se reintenta un `failed`; `None` si ya no se reintenta.
    next_attempt_at: datetime | None
