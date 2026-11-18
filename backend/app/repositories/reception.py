"""Las hojas de recepción firmadas (F6, `reception_sheets`), bajo RLS."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Employee, ReceptionSheet, WorkOrder


@dataclass(frozen=True)
class SignedSheet:
    sheet: ReceptionSheet
    # Quien la recogió o la marcó: el nombre de su ficha, que se puede renombrar.
    recorded_by_name: str


async def of_order(session: AsyncSession, order_id: UUID) -> SignedSheet | None:
    """La hoja firmada de una orden, si ya se firmó."""
    row = (
        await session.execute(
            select(ReceptionSheet, Employee.name)
            .join(Employee, Employee.id == ReceptionSheet.recorded_by_employee_id)
            .where(ReceptionSheet.work_order_id == order_id)
        )
    ).one_or_none()
    return SignedSheet(row[0], row[1]) if row else None


async def is_signed(session: AsyncSession, order_id: UUID) -> bool:
    found = await session.scalar(
        select(ReceptionSheet.id).where(ReceptionSheet.work_order_id == order_id)
    )
    return found is not None


async def erase_personal(session: AsyncSession, client_id: UUID) -> None:
    """Vacía quién trajo el coche y quién firmó en las hojas de este cliente
    (RF-15, RNF-40). Lo demás de la hoja, y la firma hasta su plazo (RF-56), se
    queda. El trigger `reception_sheets_frozen` solo lo admite con el cliente ya
    anonimizado en la base de datos."""
    await session.execute(
        update(ReceptionSheet)
        .where(
            ReceptionSheet.work_order_id.in_(
                select(WorkOrder.id).where(WorkOrder.client_id == client_id)
            ),
            or_(
                ReceptionSheet.dropped_off_by_name.is_not(None),
                ReceptionSheet.dropped_off_by_phone.is_not(None),
                ReceptionSheet.signer_name.is_not(None),
            ),
        )
        .values(dropped_off_by_name=None, dropped_off_by_phone=None, signer_name=None)
        .execution_options(synchronize_session=False)
    )
