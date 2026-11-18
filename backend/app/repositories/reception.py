"""Las hojas de recepción firmadas (F6, `reception_sheets`), bajo RLS."""

from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReceptionSheet, WorkOrder


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
