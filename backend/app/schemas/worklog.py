from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DiagnosisVersionRead(BaseModel):
    version_no: int
    text: str
    employee_name: str
    created_at: datetime


class NoteRead(BaseModel):
    seq: int
    body: str
    employee_name: str
    created_at: datetime


class Worker(BaseModel):
    id: UUID
    name: str


class WorkEntryRead(BaseModel):
    id: UUID
    # Quien lo hizo, y quien lo anotó (puede ser otro, RF-23).
    employee: Worker
    recorded_by_name: str
    description: str
    worked_on: date
    hours: Decimal | None
    voided_at: datetime | None
    can_void: bool


class WorklogRead(BaseModel):
    # La vigente primero; vacío si aún no hay diagnóstico.
    diagnosis: list[DiagnosisVersionRead]
    # El hilo por `seq`, del primero al último.
    notes: list[NoteRead]
    work_entries: list[WorkEntryRead]
    # Los que han trabajado (RF-25): de los trabajos sin anular.
    workers: list[str]


class DiagnosisSave(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # La versión desde la que se editó (0 si no había): el bloqueo optimista.
    base_version_no: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=10000)


class DiagnosisSaved(BaseModel):
    version_no: int


class NoteCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # Lo genera el navegador al empezar el borrador (RNF-22): reenviarlo tras
    # perder la conexión no anota dos veces lo mismo.
    id: UUID | None = None
    body: str = Field(min_length=1, max_length=5000)


class WorkEntryCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # Como en NoteCreate: el id del borrador, para reenviarlo sin duplicar.
    id: UUID | None = None
    # Quien lo hizo: una ficha activa del taller, tenga acceso o no.
    employee_id: UUID
    description: str = Field(min_length=1, max_length=2000)
    worked_on: date
    hours: Decimal | None = Field(
        default=None, gt=0, le=Decimal("999.99"), decimal_places=2
    )


class WorkEntryCreated(BaseModel):
    id: UUID
