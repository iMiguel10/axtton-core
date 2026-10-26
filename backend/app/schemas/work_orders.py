from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.domain.work_orders import StatusChangeCause, WorkOrderStatus, WorkOrderType


class OrderVehicle(BaseModel):
    id: UUID
    plate: str
    make: str | None
    model: str | None


class OrderClient(BaseModel):
    id: UUID
    name: str
    phone: str


class Named(BaseModel):
    id: UUID
    name: str


class OrderRef(BaseModel):
    id: UUID
    code: str


class WorkOrderRead(BaseModel):
    id: UUID
    # OT-2026-0042 (RF-21).
    code: str
    year: int
    number: int
    type: WorkOrderType
    status: WorkOrderStatus
    unrepaired: bool
    vehicle: OrderVehicle
    # El titular del vehículo al abrirla; no cambia aunque cambie el titular.
    client: OrderClient
    responsible: Named | None
    expected_delivery_at: datetime | None
    # Para destacar las que llevan más tiempo paradas (RF-24).
    last_activity_at: datetime
    created_at: datetime
    version: int


class StatusChangeRead(BaseModel):
    seq: int
    from_status: WorkOrderStatus | None
    to_status: WorkOrderStatus
    cause: StatusChangeCause
    employee_name: str | None
    by_client: bool
    note: str | None
    created_at: datetime


class WorkOrderDetailRead(WorkOrderRead):
    no_quote_reason: str | None
    warranty_of: OrderRef | None
    odometer_km: int | None
    reason: str | None
    dropped_off_by_name: str | None
    dropped_off_by_phone: str | None
    reception_notes: str | None
    delivered_at: datetime | None
    # Por `seq`, del primero al último (invariante 5: el último es el estado).
    history: list[StatusChangeRead]


class _ReceptionFields(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    odometer_km: int | None = Field(default=None, ge=0, le=9_999_999)
    reason: str | None = Field(default=None, max_length=2000)
    # Con zona horaria: una hora sin zona no dice qué instante es.
    expected_delivery_at: AwareDatetime | None = None
    dropped_off_by_name: str | None = Field(default=None, max_length=200)
    dropped_off_by_phone: str | None = Field(default=None, max_length=30)
    reception_notes: str | None = Field(default=None, max_length=2000)
    # Puede quedar sin asignar al abrirla (RF-25).
    responsible_employee_id: UUID | None = None


class WorkOrderCreate(_ReceptionFields):
    vehicle_id: UUID
    type: WorkOrderType
    # Solo en una orden de garantía: la orden entregada de la que viene (§6).
    warranty_of_id: UUID | None = None


class WorkOrderCreated(BaseModel):
    id: UUID
    code: str


class WorkOrderUpdate(_ReceptionFields):
    """Solo los campos presentes se cambian (exclude_unset al usarlo). Todos
    son opcionales en la orden, así que se pueden vaciar con null."""

    version: int
