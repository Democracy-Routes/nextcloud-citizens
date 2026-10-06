# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A facilitator's own phone beside a table (0.7)."""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from citizens.db.models.base import Base, TZDateTime, new_uuid, utcnow


class FacilitatorSession(Base):
    """The bearer behind a facilitator's page: one table, one assembly, a few
    hours. Never a recorder — it writes prompts to the table's phones, raises
    the table's hand and reads what the table's phones read."""

    __tablename__ = "facilitator_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    assembly_id: Mapped[str] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), index=True
    )
    table_number: Mapped[int] = mapped_column(Integer)
    # the FACILITATE_TABLE code it came through, for the audit trail
    invite_id: Mapped[str | None] = mapped_column(
        ForeignKey("recorder_invites.id", ondelete="SET NULL")
    )
    # only the SHA-256 of the bearer is stored
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime())
    last_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    last_seen_message_id: Mapped[int | None] = mapped_column(Integer)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime())
