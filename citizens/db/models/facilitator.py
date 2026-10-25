# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A facilitator's own phone beside a table (0.7)."""

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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


class TableFacilitation(Base):
    """A table's own AI-facilitator switch, overriding the assembly's level:
    set from the table's phone or the Live tab's "Pause AI"."""

    __tablename__ = "table_facilitation"
    __table_args__ = (UniqueConstraint("assembly_id", "table_number", name="uq_table_facilitation"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    assembly_id: Mapped[str] = mapped_column(ForeignKey("assemblies.id", ondelete="CASCADE"))
    table_number: Mapped[int] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String(12))
    updated_by: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)


class FacilitatorIntervention(Base):
    """One piece of advice the AI facilitator produced for one table."""

    __tablename__ = "facilitator_interventions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    assembly_id: Mapped[str] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), index=True
    )
    round_id: Mapped[str | None] = mapped_column(ForeignKey("rounds.id", ondelete="SET NULL"))
    table_number: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    delivered_to: Mapped[str] = mapped_column(String(16))
    message_id: Mapped[int | None] = mapped_column(Integer)
    facilitator_session_id: Mapped[str | None] = mapped_column(String(36))
    caption_t: Mapped[float | None] = mapped_column(Float)
    model: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    sent_to_table_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    dismissed_at: Mapped[datetime | None] = mapped_column(TZDateTime())


class FacilitatorFeedback(Base):
    """A thumb under an intervention — from the table's phone or the facilitator's."""

    __tablename__ = "facilitator_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    intervention_id: Mapped[str] = mapped_column(
        ForeignKey("facilitator_interventions.id", ondelete="CASCADE"), index=True
    )
    table_number: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16))
    helpful: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
