# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assembly-core entities (brief §45–§46)."""

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from citizens.db.models.base import Base, TZDateTime, new_uuid, utcnow

ASSEMBLY_STATUSES = ("DRAFT", "READY", "ACTIVE", "PROCESSING", "REVIEW", "COMPLETE")
ROUND_STATUSES = ("NOT_STARTED", "ACTIVE", "ENDED", "PROCESSING", "READY_FOR_REVIEW")
# "assembly": an organized event the user created as such, holding rounds.
# "session": the container behind a standalone Session (services/sessions.py)
# — persisted this way because every storage path, ownership check and sweep
# is keyed by assembly_id, but never shown to the user as an assembly.
ASSEMBLY_KINDS = ("assembly", "session")


class Assembly(Base):
    __tablename__ = "assemblies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    kind: Mapped[str] = mapped_column(String(16), default="assembly", server_default="assembly")
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(10), default="en")
    # Record now: nobody chose the language, so the first final transcript's
    # detected language becomes it (services/transcription.py); a wizard's
    # explicit choice, or a manual change, leaves this off
    language_auto: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    scheduled_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    # "orchestrated": facilitator starts/ends rounds for all tables at once;
    # "independent": each table records the shared questions on its own schedule
    recording_mode: Mapped[str] = mapped_column(String(16), default="orchestrated")
    expected_participants: Mapped[int] = mapped_column(Integer, default=0)
    default_table_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(64), index=True)
    # organizer-provided context appended to the AI analysis prompts
    # (topic, glossary) on top of the instance-wide admin instructions
    analysis_instructions: Mapped[str] = mapped_column(Text, default="")
    # when set, table phones may view/download the (approved-findings) report
    report_published_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    # the organizer declared the assembly finished: no new recordings, and the
    # report becomes final (a snapshot is frozen so reopening cannot change
    # what participants already read)
    closed_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    final_report_json: Mapped[str | None] = mapped_column(Text)
    final_report_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    # how the discussion developed across sessions (services/analysis.py
    # analyze_assembly): narrative, stages, what was carried forward
    synthesis_json: Mapped[str | None] = mapped_column(Text)
    synthesis_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    # days of audio retention after closing, overriding the instance default;
    # NULL = follow the default, 0 = keep indefinitely
    audio_retention_days: Mapped[int | None] = mapped_column(Integer())
    audio_purged_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    # The organizer asked the table phones to delete their local copies. The
    # server cannot push to a phone, so this travels on the status poll each
    # recorder already makes every few seconds. Set once and left set: a phone
    # that reopens days later should still honour it.
    device_audio_purge_requested_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    # Whether the standing purge request came from close_assembly (True) or an
    # organizer pressing the button (False). Reopening withdraws only the
    # automatic kind — keying that off the toggle's CURRENT value meant turning
    # auto-purge off between close and reopen left the request standing: the
    # first status poll after the reopen told every phone to delete each new
    # recording the moment it reached AUDIO_READY. NULL for rows written
    # before this column existed.
    purge_requested_automatically: Mapped[bool | None] = mapped_column(Boolean)
    # Ask the phones automatically when the session is closed. On by default:
    # the case this exists for is participants recording on their own devices,
    # where leaving the audio behind is the surprising outcome. An organizer
    # using the organisation's own phones can turn it off and keep the local
    # copies until the export has been downloaded and checked.
    auto_purge_device_audio: Mapped[bool] = mapped_column(Boolean, default=True)
    # Names to replace with stand-ins before the transcript is sent to the
    # analysis model. Free text, one per line or comma-separated: the organizer
    # knows who is in the room, and a guess would mangle ordinary words.
    redact_names: Mapped[str] = mapped_column(Text, default="")
    # 'required': a table records only once one registered person there has
    # consented (services/consent.py); 'optional': the notice is shown and
    # registration offered, nothing is blocked. Organized assemblies start
    # 'required', spontaneous Sessions 'optional'.
    participant_consent: Mapped[str] = mapped_column(
        String(16), default="optional", server_default="optional"
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    rounds: Mapped[list["Round"]] = relationship(
        back_populates="assembly", cascade="all, delete-orphan", order_by="Round.position"
    )
    participants: Mapped[list["Participant"]] = relationship(
        back_populates="assembly", cascade="all, delete-orphan", order_by="Participant.label"
    )
    invites: Mapped[list["RecorderInvite"]] = relationship(
        back_populates="assembly", cascade="all, delete-orphan"
    )


class Round(Base):
    __tablename__ = "rounds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    assembly_id: Mapped[str] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200), default="")
    question: Mapped[str] = mapped_column(Text, default="")
    # What the discussion should produce ("three concrete proposals"), as
    # distinct from what it is about (the question). Optional; NULL on every
    # round made before 0.7 and on any session that does not state one.
    objective: Mapped[str | None] = mapped_column(Text)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(20), default="NOT_STARTED")
    analysis_summary: Mapped[str] = mapped_column(Text, default="")
    # Is the cross-table clustering current? input bumps whenever the findings
    # it reads change (a table re-analysed, an organizer rejecting or editing);
    # applied is set from the input revision a run STARTED from. Stale ⇔
    # input > applied. A timestamp cannot express this: a job's updated_at is
    # stamped when the runner marks it done — after the model call — so a
    # review landing mid-run looked older than the run that never saw it.
    analysis_input_revision: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    analysis_applied_revision: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(TZDateTime())

    assembly: Mapped[Assembly] = relationship(back_populates="rounds")
    tables: Mapped[list["Table"]] = relationship(
        back_populates="round", cascade="all, delete-orphan", order_by="Table.number"
    )


class Table(Base):
    __tablename__ = "tables"
    __table_args__ = (UniqueConstraint("round_id", "number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(100), default="")
    # a visual cue beside the number (domain/tables.py); assigned from the
    # number, repeats after six, and nothing depends on it for correctness
    color_key: Mapped[str] = mapped_column(String(16), default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="IDLE")

    round: Mapped[Round] = relationship(back_populates="tables")
    assignments: Mapped[list["TableAssignment"]] = relationship(
        back_populates="table", cascade="all, delete-orphan"
    )


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("assembly_id", "label"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    assembly_id: Mapped[str] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    # ORGANIZER (the list, the CSV) or registered at a table phone: TABLE_DEVICE
    # on the shared phone, SELF_PHONE through the table's registration code
    source: Mapped[str] = mapped_column(String(16), default="ORGANIZER", server_default="ORGANIZER")
    # where a table-phone registration happened — the table is then known
    # without anyone typing it; the round is the one being set up at the time
    registered_table_number: Mapped[int | None] = mapped_column(Integer)
    registered_round_id: Mapped[str | None] = mapped_column(
        ForeignKey("rounds.id", ondelete="SET NULL")
    )
    registered_session_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    assembly: Mapped[Assembly] = relationship(back_populates="participants")


class TableAssignment(Base):
    __tablename__ = "table_assignments"
    # one table per participant per round
    __table_args__ = (UniqueConstraint("round_id", "participant_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id", ondelete="CASCADE"), index=True)
    table_id: Mapped[str] = mapped_column(ForeignKey("tables.id", ondelete="CASCADE"), index=True)
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), index=True
    )

    table: Mapped[Table] = relationship(back_populates="assignments")
    participant: Mapped[Participant] = relationship()


#: What scanning the code does. JOIN_TABLE is the printed table code, reusable
#: for thirty days so a replacement phone can rescan the poster. The other two
#: are made by a phone that already joined, shown as a QR for the next phone,
#: short-lived and single-use — and the scanner never chooses between them.
INVITE_PURPOSES = ("JOIN_TABLE", "ADD_RECORDER_TO_TABLE", "ADD_TABLE")


class RecorderInvite(Base):
    """A capability a phone redeems by scanning: a table code or an action code.

    One row, one token mechanism (hash, vault, rate limit, brute-force
    protection, the #/join route) for every purpose; `purpose` says which.
    """

    __tablename__ = "recorder_invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    assembly_id: Mapped[str] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(
        String(32), default="JOIN_TABLE", server_default="JOIN_TABLE"
    )
    # the table this code concerns; NULL for ADD_TABLE, whose number is
    # allocated when the code is consumed
    table_number: Mapped[int | None] = mapped_column(Integer)
    # the Session (round) an action code was made in — scope and audit, not a
    # restriction on where the table lives: tables span every round
    round_id: Mapped[str | None] = mapped_column(ForeignKey("rounds.id", ondelete="SET NULL"))
    # action codes are redeemed once: consumed_at is claimed atomically by the
    # first scan (services/capabilities.py) and a second scan is refused
    single_use: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    consumed_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    # the recorder session that made an action code. A plain id, not a foreign
    # key: recorder_sessions already references this table
    created_by_session_id: Mapped[str | None] = mapped_column(String(36))
    # the SHA-256 hex digest is what join verification uses; the token itself
    # is additionally kept encrypted (app-secret Fernet) so the organizer can
    # re-view and re-print QR sheets at any time
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_encrypted: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    # a QR code is a secret printed on a poster in a public room; NULL means an
    # invite issued before expiry existed and is treated as never expiring
    expires_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime())

    assembly: Mapped[Assembly] = relationship(back_populates="invites")
