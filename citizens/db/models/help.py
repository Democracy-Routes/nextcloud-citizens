# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A table raising its hand for the organizer (0.7)."""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from citizens.db.models.assembly import Assembly
from citizens.db.models.base import Base, TZDateTime, new_uuid, utcnow

#: what the table can ask for — a phrase on the phone, a word for the organizer
HELP_KINDS = ("TECHNICAL", "ORGANIZER", "PROCESS")


class HelpRequest(Base):
    __tablename__ = "help_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    assembly_id: Mapped[str] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), index=True
    )
    # the session running when the hand went up, if any
    round_id: Mapped[str | None] = mapped_column(ForeignKey("rounds.id", ondelete="SET NULL"))
    table_number: Mapped[int] = mapped_column(Integer)
    slot: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    kind: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    acknowledged_by: Mapped[str | None] = mapped_column(String(64))

    assembly: Mapped[Assembly] = relationship(Assembly)
