"""El acceso del cliente al portal (F4, arquitectura §7.2, decisión 0006).

Un enlace mágico es de un taller y de un cliente de ese taller. Por eso vive en
una tabla del taller, con RLS forzada (migración 0016portallinks): al consumirlo,
la transacción fija el taller que dice la URL, y el enlace de otro taller ni se
ve. Es lo que impide que cambiar el taller de la URL abra una sesión en él (T5).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin


class PortalLink(IdMixin, CreatedAtMixin, Base):
    """Un enlace mágico emitido para un cliente de un taller (RF-40, RF-45).

    Del enlace solo se guarda el hash, como con las invitaciones. Es de un solo
    uso (RNF-04): consumirlo escribe `used_at`, y un trigger impide volver a
    tocar la fila. No guarda el email: se lee del cliente al consumirlo, y
    cambiar el email o anonimizar al cliente revoca los enlaces pendientes.
    """

    __tablename__ = "portal_links"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        ForeignKeyConstraint(
            ["client_id", "workshop_id"], ["clients.id", "clients.workshop_id"]
        ),
        # Usado o revocado, nunca las dos cosas: es la causa por la que se cerró.
        CheckConstraint("used_at IS NULL OR revoked_at IS NULL", name="closed_once"),
        CheckConstraint("expires_at > created_at", name="expires_after_creation"),
        # Revocar los pendientes de un cliente (cambio de email, anonimizar).
        Index("ix_portal_links_workshop_id_client_id", "workshop_id", "client_id"),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    client_id: Mapped[UUID]
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
