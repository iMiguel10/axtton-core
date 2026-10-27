from datetime import date, datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.domain.work_orders import (
    NoQuoteReason,
    PaymentMethod,
    PaymentStatus,
    StatusChangeCause,
    WorkOrderStatus,
    WorkOrderType,
)


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
    # Si es un deshacer, el `seq` del cambio que compensa.
    undoes_seq: int | None
    employee_name: str | None
    by_client: bool
    note: str | None
    created_at: datetime


class TransitionRead(BaseModel):
    """Un cambio que quien consulta puede hacer ahora (domain.TRANSITIONS)."""

    to_status: WorkOrderStatus
    needs_note: bool
    unrepaired: bool


class WorkOrderDetailRead(WorkOrderRead):
    no_quote_reason: str | None
    warranty_of: OrderRef | None
    odometer_km: int | None
    reason: str | None
    dropped_off_by_name: str | None
    dropped_off_by_phone: str | None
    reception_notes: str | None
    delivered_at: datetime | None
    # El cobro (RF-28): solo una cobrada lleva forma, importe y fecha.
    payment_status: PaymentStatus
    payment_method: PaymentMethod | None
    paid_amount_cents: int | None
    paid_on: date | None
    # Por `seq`, del primero al último (invariante 5: el último es el estado).
    history: list[StatusChangeRead]
    # Lo que puede hacer quien la consulta, según su rol en este taller. Es una
    # comodidad para la interfaz: el servidor lo vuelve a comprobar al pedirlo.
    allowed_transitions: list[TransitionRead]
    can_undo: bool
    can_mark_no_quote: bool
    can_record_payment: bool


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


class StatusChange(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    version: int
    to_status: WorkOrderStatus
    # Obligatoria para cancelar y para "sin reparar" (§6).
    note: str | None = Field(default=None, max_length=2000)


class VersionOnly(BaseModel):
    version: int


class NoQuoteChange(BaseModel):
    version: int
    # Nulo: deja de estar marcada.
    reason: NoQuoteReason | None


class PaymentChange(BaseModel):
    """El cobro entero, no un parche: lo que no venga queda vacío. Si está
    cobrada, forma de pago, importe y fecha son obligatorios (el service)."""

    version: int
    status: PaymentStatus
    method: PaymentMethod | None = None
    # En céntimos, como todos los importes (arquitectura §3).
    amount_cents: int | None = Field(default=None, gt=0, le=10_000_000_00)
    paid_on: date | None = None


class UnpaidOrderRead(WorkOrderRead):
    """Una entregada pendiente de cobro (RF-29). El importe a cobrar llegará con
    los presupuestos (F3): hoy no hay de dónde sacarlo."""

    delivered_at: datetime
    # De la entrega a hoy, en días del taller.
    days_pending: int
