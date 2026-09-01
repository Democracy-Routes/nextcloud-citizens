# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recorder sessions, recordings and audio chunks (brief §14, §17, §23–§24, §46)."""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from citizens.db.models.base import Base, TZDateTime, new_uuid, utcnow

RECORDING_STATES = (
    "CREATED",
    "RECORDING",
    "FINALIZING",
    "WAITING_FOR_CHUNKS",
    "ASSEMBLING",
    "AUDIO_READY",
    "TRANSCRIBING",
    "TRANSCRIBED",
    "ANALYZING",
    "READY_FOR_REVIEW",
    "REVIEWED",
    # error states
    "UPLOAD_INCOMPLETE",
    "AUDIO_INVALID",
    "TRANSCRIPTION_FAILED",
    "ANALYSIS_FAILED",
)


class RecorderSession(Base):
    __tablename__ = "recorder_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    invite_id: Mapped[str] = mapped_column(
        ForeignKey("recorder_invites.id", ondelete="CASCADE"), index=True
    )
    assembly_id: Mapped[str] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), index=True
    )
    table_number: Mapped[int] = mapped_column(Integer)
    # only the SHA-256 of the bearer token is stored
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime())
    last_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    # latest device-reported health (heartbeat payload), for the live dashboard
    last_status_json: Mapped[str] = mapped_column(Text, default="{}")
    last_status_at: Mapped[datetime | None] = mapped_column(TZDateTime())


class Recording(Base):
    __tablename__ = "recordings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    assembly_id: Mapped[str] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), index=True
    )
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id", ondelete="CASCADE"), index=True)
    table_id: Mapped[str] = mapped_column(ForeignKey("tables.id", ondelete="CASCADE"), index=True)
    table_number: Mapped[int] = mapped_column(Integer)
    recorder_session_id: Mapped[str] = mapped_column(
        ForeignKey("recorder_sessions.id", ondelete="SET NULL"), nullable=True
    )
    state: Mapped[str] = mapped_column(String(24), default="CREATED", index=True)
    mime_type: Mapped[str] = mapped_column(String(80), default="")
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    total_chunks: Mapped[int | None] = mapped_column(Integer)
    received_chunks: Mapped[int] = mapped_column(Integer, default=0)
    canonical_audio_path: Mapped[str] = mapped_column(Text, default="")
    duration_seconds: Mapped[float | None] = mapped_column()
    sha256: Mapped[str] = mapped_column(String(64), default="")
    error_code: Mapped[str] = mapped_column(String(64), default="")
    # neutral AI description of the table discussion (always produced by analysis)
    analysis_summary: Mapped[str] = mapped_column(Text, default="")
    # audio deliberately removed (Files tab / retention); the transcript,
    # findings and report survive, so the row stays with its metadata
    audio_deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    # this table's phone was replaced mid-round and another device took over.
    # The recording is still real and still transcribed — it holds most of the
    # round — but it must stop blocking a new one for the same table, which
    # state alone cannot express: it may legitimately be ASSEMBLING or
    # TRANSCRIBED while the replacement is already recording.
    superseded_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    chunks: Mapped[list["AudioChunk"]] = relationship(
        back_populates="recording", cascade="all, delete-orphan", order_by="AudioChunk.sequence_number"
    )


class AudioChunk(Base):
    __tablename__ = "audio_chunks"
    __table_args__ = (UniqueConstraint("recording_id", "sequence_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    recording_id: Mapped[str] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE"), index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    recording: Mapped[Recording] = relationship(back_populates="chunks")
