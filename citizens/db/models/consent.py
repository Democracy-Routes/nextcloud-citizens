# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Individual consent recorded at the table (0.7): the notice as shown, and
one row per consent act — see migration 0030 for the reasoning."""

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from citizens.db.models.base import Base, TZDateTime, new_uuid, utcnow

#: how a consent was given: on the table's phone, on the person's own phone
#: (0.7), on paper entered by the organizer (reserved)
CONSENT_METHODS = ("TABLE_DEVICE", "SELF_PHONE", "PAPER")
#: where a participant row came from
PARTICIPANT_SOURCES = ("ORGANIZER", "TABLE_DEVICE", "SELF_PHONE")
#: an assembly's rule: must someone at the table consent before it records?
CONSENT_MODES = ("required", "optional")


class ConsentNotice(Base):
    """The exact text a person read, kept once per hash."""

    __tablename__ = "consent_notices"

    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(16))
    language: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class ParticipantConsent(Base):
    __tablename__ = "participant_consents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    assembly_id: Mapped[str] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), index=True
    )
    # erasing the person erases their consent record — counts survive in audit
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), index=True
    )
    round_id: Mapped[str | None] = mapped_column(ForeignKey("rounds.id", ondelete="SET NULL"))
    table_number: Mapped[int | None] = mapped_column(Integer)
    recorder_session_id: Mapped[str | None] = mapped_column(String(36))
    method: Mapped[str] = mapped_column(String(16))
    notice_hash: Mapped[str] = mapped_column(ForeignKey("consent_notices.hash"))
    notice_version: Mapped[str] = mapped_column(String(16))
    notice_language: Mapped[str] = mapped_column(String(10))
    notice_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    recording_consent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    transcription_consent: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    analysis_consent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # short anonymous quotations in the published report
    publication_consent: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    # the server's clock, never the phone's
    confirmed_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    withdrawn_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class ParticipantSession(Base):
    """A person who registered on their own phone: the bearer behind their
    page (where they are registered, their consent, the published report)."""

    __tablename__ = "participant_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), index=True
    )
    assembly_id: Mapped[str] = mapped_column(ForeignKey("assemblies.id", ondelete="CASCADE"))
    # only the SHA-256 of the bearer is stored
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime())
    last_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime())
