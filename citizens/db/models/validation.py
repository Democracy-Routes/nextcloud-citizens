# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A participant's word on their table's published summary (0.7)."""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from citizens.db.models.base import Base, TZDateTime, new_uuid, utcnow

VERDICTS = ("LOOKS_RIGHT", "MISSING")


class SummaryValidation(Base):
    __tablename__ = "summary_validations"
    __table_args__ = (UniqueConstraint("round_id", "participant_id", name="uq_summary_validation_once"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    assembly_id: Mapped[str] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), index=True
    )
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id", ondelete="CASCADE"))
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id", ondelete="CASCADE"))
    # the table whose summary was judged, as seated at the time
    table_number: Mapped[int | None] = mapped_column(Integer)
    verdict: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
