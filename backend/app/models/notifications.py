"""La bandeja de salida de avisos al cliente (F5 paso 4, arquitectura §8).

Una fila es un aviso: nace en la transacción del cambio que lo provoca
(invariante 8) y el worker la envía después. No guarda el email del cliente ni
el texto del correo, que se leen y se escriben al enviar, ni el texto de un
error del servidor, que podría llevar el email (RNF-40): solo el motivo como
código y, si lo hay, el código SMTP.

Ninguna fila se borra: es lo que impide avisar dos veces del mismo motivo
(`UNIQUE (workshop_id, dedupe_key)`, RF-62), y el taller ve en la orden qué se
envió (RF-69).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.notifications import (
    MAX_ATTEMPTS,
    FailureReason,
    NotificationKind,
    NotificationStatus,
)
from app.domain.work_orders import sql_in
from app.models.base import Base, CreatedAtMixin, IdMixin, UpdatedAtMixin


class Notification(IdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("id", "workshop_id"),
        # "Nunca dos veces por el mismo motivo" (RF-62): el mismo motivo es la
        # misma fila, y crear el aviso es INSERT … ON CONFLICT DO NOTHING.
        UniqueConstraint("workshop_id", "dedupe_key"),
        ForeignKeyConstraint(
            ["client_id", "workshop_id"], ["clients.id", "clients.workshop_id"]
        ),
        ForeignKeyConstraint(
            ["work_order_id", "workshop_id"],
            ["work_orders.id", "work_orders.workshop_id"],
        ),
        ForeignKeyConstraint(
            ["quote_id", "workshop_id"], ["quotes.id", "quotes.workshop_id"]
        ),
        CheckConstraint(sql_in("kind", NotificationKind), name="kind"),
        CheckConstraint(sql_in("status", NotificationStatus), name="status"),
        CheckConstraint(f"attempts BETWEEN 0 AND {MAX_ATTEMPTS}", name="attempts"),
        CheckConstraint(
            f"failure_reason IS NULL OR {sql_in('failure_reason', FailureReason)}",
            name="failure_reason",
        ),
        # Cada estado lleva lo suyo, y nada más.
        CheckConstraint(
            "(status = 'claimed') = (claimed_at IS NOT NULL)", name="claimed_at"
        ),
        CheckConstraint("(status = 'sent') = (sent_at IS NOT NULL)", name="sent_at"),
        CheckConstraint(
            "next_attempt_at IS NULL OR status = 'failed'", name="next_attempt_at"
        ),
        CheckConstraint(
            "(failure_reason IS NULL) = (status IN ('pending', 'claimed', 'sent'))",
            name="failure_reason_status",
        ),
        CheckConstraint(
            "smtp_code IS NULL OR smtp_code BETWEEN 100 AND 599", name="smtp_code"
        ),
        # El despachador: lo que toca enviar o reintentar.
        Index(
            "ix_notifications_pending_due",
            "scheduled_for",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_notifications_retry_due",
            "next_attempt_at",
            postgresql_where=text("status = 'failed' AND next_attempt_at IS NOT NULL"),
        ),
        # El barrido de reclamos abandonados.
        Index(
            "ix_notifications_claimed",
            "claimed_at",
            postgresql_where=text("status = 'claimed'"),
        ),
        # Los avisos de una orden (RF-69).
        Index(
            "ix_notifications_workshop_id_work_order_id", "workshop_id", "work_order_id"
        ),
    )

    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    kind: Mapped[str] = mapped_column(String(30))
    # El motivo (arquitectura §8): `quote_sent:<quote_id>`, `ready:<orden>:<seq>`…
    dedupe_key: Mapped[str] = mapped_column(String(200))
    # A quién: el cliente de la orden. Su email se lee al enviar.
    client_id: Mapped[UUID]
    # De qué: la orden y, si es de un presupuesto, su versión.
    work_order_id: Mapped[UUID | None]
    quote_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(
        String(20), server_default=NotificationStatus.PENDING.value
    )
    # Cuándo se puede enviar; los de F5, en el acto.
    scheduled_for: Mapped[datetime] = mapped_column(
        server_default=text("clock_timestamp()")
    )
    # Intentos hechos (cada reclamo es uno) y el último reclamo, desde el que
    # mide el barrido de abandonados.
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    claimed_at: Mapped[datetime | None]
    # Solo en `failed` con intentos por delante.
    next_attempt_at: Mapped[datetime | None]
    sent_at: Mapped[datetime | None]
    failure_reason: Mapped[str | None] = mapped_column(String(30))
    # El código de la respuesta del servidor, si la hubo (550, 421…).
    smtp_code: Mapped[int | None] = mapped_column(SmallInteger)
