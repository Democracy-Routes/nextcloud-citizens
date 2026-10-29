# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Polis statement seeds: what an assembly hands to a Polis conversation.

A seed is one short statement a participant can agree or disagree with. The
analysis model writes them from the approved findings; the organizer edits,
approves or rejects each one; approved seeds are exported as a file for
Polis. They carry statement text only: evidence, speaker labels and names
never leave Citizens through this table.
"""

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from citizens.db.models.base import Base, TZDateTime, new_uuid, utcnow

SEED_STATUSES = ("DRAFT", "APPROVED", "REJECTED", "EXPORTED")
#: statuses an export takes (EXPORTED stays exportable: a second download
#: must carry the same statements)
EXPORTABLE_STATUSES = ("APPROVED", "EXPORTED")
SEED_ORIGINS = ("ai", "manual")
#: PolisOrbis's seed box takes 400 characters; shorter reads better in Polis
SEED_MAX_CHARS = 400
SEED_SOFT_CHARS = 140


class StatementSeed(Base):
    __tablename__ = "statement_seeds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    assembly_id: Mapped[str] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), index=True
    )
    # the finding this seed was written from; NULL once a re-run of the
    # analysis replaced that finding (the seed is then marked stale)
    finding_id: Mapped[str | None] = mapped_column(
        ForeignKey("findings.id", ondelete="SET NULL"), index=True
    )
    text: Mapped[str] = mapped_column(Text, default="")
    # as the model wrote it; text != source_text means the organizer edited it
    source_text: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(10), default="en")
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    position: Mapped[int] = mapped_column(Integer, default=0)
    origin: Mapped[str] = mapped_column(String(8), default="ai")
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(64))
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    exported_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    # reserved for the push to a Polis instance
    polis_conversation_id: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    @property
    def edited(self) -> bool:
        return self.origin == "ai" and self.text != self.source_text

    @property
    def touched(self) -> bool:
        """Reviewed or rewritten by a person: regeneration must keep it."""
        return self.status != "DRAFT" or self.edited or self.origin == "manual"
