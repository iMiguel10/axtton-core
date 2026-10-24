from uuid import UUID

from pydantic import BaseModel


class WorkOrderRead(BaseModel):
    id: UUID
    status: str
    client_name: str
    plate: str
    quote_id: UUID | None
    quote_status: str | None
