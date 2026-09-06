# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recorder sessions, recordings and chunk intake (brief §14, §17, §23)."""

import hashlib
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.db.models import RecorderSession, Recording, Round, Table
from citizens.db.models.base import utcnow
from citizens.db.models.recording import AudioChunk
from citizens.logging_setup import get_logger
from citizens.security.recorder_tokens import generate_token, hash_token
from citizens.services import invites as invite_svc
from citizens.services import provider_config
from citizens.services.jobs import enqueue_job
from citizens.services.recording_states import transition
from citizens.storage.paths import chunk_path, recording_dir
from citizens.storage.space import require_room

log = get_logger(__name__)

SESSION_LIFETIME_HOURS = 16
# how stale the device's "last contact" may be before we spend a write on it
LAST_SEEN_RESOLUTION = 15.0
MAX_CHUNK_BYTES = 5 * 1024 * 1024


def create_session_from_invite(session: Session, token: str) -> tuple[RecorderSession, str]:
    invite = invite_svc.find_active_by_token(session, token)
    if invite is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked invite")
    invite.last_used_at = utcnow()
    bearer = generate_token()
    recorder_session = RecorderSession(
        invite_id=invite.id,
        assembly_id=invite.assembly_id,
        table_number=invite.table_number,
        token_hash=hash_token(bearer),
        expires_at=utcnow() + timedelta(hours=SESSION_LIFETIME_HOURS),
    )
    session.add(recorder_session)
    session.flush()
    log.info(
        "recorder_session_created",
        assembly_id=invite.assembly_id,
        table_number=invite.table_number,
    )
    return recorder_session, bearer


def get_session_by_bearer(
    session: Session, bearer: str, touch: bool = True
) -> RecorderSession:
    recorder_session = session.execute(
        select(RecorderSession).where(RecorderSession.token_hash == hash_token(bearer))
    ).scalar_one_or_none()
    if (
        recorder_session is None
        or recorder_session.revoked_at is not None
        or recorder_session.expires_at < utcnow()
    ):
        raise HTTPException(status_code=401, detail="Recorder session invalid or expired")
    # Touch last_seen_at at most every LAST_SEEN_RESOLUTION. Writing it on every
    # request made even a pure caption poll take SQLite's single write slot —
    # about 12 write-locks a second at twenty tables, purely for bookkeeping the
    # monitor only shows to the nearest few seconds.
    now = utcnow()
    if touch and (
        recorder_session.last_seen_at is None
        or (now - recorder_session.last_seen_at).total_seconds() >= LAST_SEEN_RESOLUTION
    ):
        recorder_session.last_seen_at = now
    return recorder_session


# a recording in one of these states is failed/abandoned: re-recording allowed
RERECORDABLE_STATES = ("CREATED", "AUDIO_INVALID", "UPLOAD_INCOMPLETE")

# the audio is validated and safe server-side (assembly onward)
COMPLETED_STATES = (
    "AUDIO_READY", "TRANSCRIBING", "TRANSCRIBED", "TRANSCRIPTION_FAILED",
    "ANALYZING", "READY_FOR_REVIEW", "REVIEWED", "ANALYSIS_FAILED",
)


def assembly_complete(session: Session, assembly, analysis_enabled: bool | None = None) -> bool:
    """True when EVERY table has a completed recording for EVERY round.

    Drives the independent-mode auto-availability of the report on phones:
    with analysis enabled, every round must also carry its cross-table AI
    summary so the auto-shown report is never empty.

    `analysis_enabled` lets a caller that already read the setting pass it in.
    Reading it here is an OCS call to Nextcloud, and /public/join runs this
    while holding SQLite's writer slot — twenty tables scanning QR codes in the
    same minute is exactly when that starves the chunk uploads. Left at None it
    reads the (30 s cached) setting itself, so every other caller is unchanged.
    """
    expected = set(range(1, assembly.default_table_count + 1))
    if not expected or not assembly.rounds:
        return False
    completed_by_round: dict[str, set[int]] = {}
    for recording in session.execute(
        select(Recording).where(
            Recording.assembly_id == assembly.id,
            Recording.state.in_(COMPLETED_STATES),
        )
    ).scalars():
        completed_by_round.setdefault(recording.round_id, set()).add(recording.table_number)
    if analysis_enabled is None:
        analysis_enabled = provider_config.analysis_enabled_cached()
    analysis_on = analysis_enabled
    for round_ in assembly.rounds:
        if not expected.issubset(completed_by_round.get(round_.id, set())):
            return False
        if analysis_on and not round_.analysis_summary:
            return False
    return True


def assembly_progress(session: Session, assembly) -> dict:
    """Participation coverage — drives interim/final wording everywhere."""
    expected = list(range(1, assembly.default_table_count + 1))
    rounds = list(assembly.rounds)
    rounds_by_table: dict[int, set[str]] = {}
    for recording in session.execute(
        select(Recording).where(
            Recording.assembly_id == assembly.id,
            Recording.state.in_(COMPLETED_STATES),
        )
    ).scalars():
        rounds_by_table.setdefault(recording.table_number, set()).add(recording.round_id)

    round_ids = {round_.id for round_ in rounds}
    tables_complete = [
        number for number, done in rounds_by_table.items() if round_ids and round_ids.issubset(done)
    ]
    return {
        "tables_expected": len(expected),
        "tables_complete": len(tables_complete),
        "tables_contributed": len(rounds_by_table),
        "tables_missing": [n for n in expected if n not in rounds_by_table],
        "rounds_total": len(rounds),
        "rounds_analyzed": sum(1 for round_ in rounds if round_.analysis_summary),
        "complete": assembly_complete(session, assembly),
    }


#: How long a recording may go without a chunk before a replacement phone may
#: take the table over. Chunks arrive every ~10 s (CHUNK_INTERVAL_MS), so two
#: minutes is roughly twelve missed ones — well past any plausible hiccup, and
#: far enough from the monitor's 45 s "stale" warning that the irreversible
#: action needs more evidence than the advisory one.
STALLED_DEVICE_SECONDS = 120


def device_has_gone_silent(recording: Recording) -> bool:
    """Has this recording's phone stopped sending anything at all?

    `updated_at` bumps on every received chunk, so it measures the arrival of
    audio rather than the liveness of a heartbeat — which is what actually
    matters for deciding whether a recording is still being made.
    """
    if recording.state != "RECORDING" or recording.updated_at is None:
        return False
    return (utcnow() - recording.updated_at).total_seconds() > STALLED_DEVICE_SECONDS


def _release_silent_recording(
    session: Session, recording: Recording, error_code: str = "DEVICE_SILENT"
) -> None:
    from citizens.services.live_captions import LIVE_CAPTIONS

    recording.error_code = error_code
    recording.superseded_at = utcnow()
    transition(recording, "UPLOAD_INCOMPLETE")
    session.flush()
    # nothing else will ever end its caption session; see release_stalled_recording
    LIVE_CAPTIONS.finish(recording.id)
    log.warning(
        "device_silent_recording_released",
        recording_id=recording.id,
        table_number=recording.table_number,
        received_chunks=recording.received_chunks,
        error_code=error_code,
    )


def start_recording(
    session: Session, recorder_session: RecorderSession, round_id: str, mime_type: str
) -> Recording:
    round_ = session.get(Round, round_id)
    if round_ is None or round_.assembly_id != recorder_session.assembly_id:
        raise HTTPException(status_code=404, detail="Round not found")
    table = session.execute(
        select(Table).where(Table.round_id == round_id, Table.number == recorder_session.table_number)
    ).scalar_one_or_none()
    if table is None:
        raise HTTPException(status_code=422, detail="This round has no table with your number")

    # a closed session accepts no new audio: the report is already final
    if round_.assembly.closed_at is not None:
        raise HTTPException(
            status_code=409,
            detail="This assembly has been closed by the organizer",
        )

    # orchestrated assemblies record only while the facilitator has the round
    # open; independent assemblies let each table record on its own schedule
    if round_.assembly.recording_mode == "orchestrated" and round_.status != "ACTIVE":
        raise HTTPException(
            status_code=409, detail="The facilitator has not started this round yet"
        )

    # one healthy recording per table+round: prevents accidental extra
    # recordings after a table already finished (unless the earlier attempt failed)
    existing = session.execute(
        select(Recording).where(
            Recording.round_id == round_id,
            Recording.table_id == table.id,
            Recording.state.notin_(RERECORDABLE_STATES),
            # a superseded recording is still progressing towards a transcript
            # — it holds most of the round — but its phone is gone, so it must
            # not keep the table from recording the rest
            Recording.superseded_at.is_(None),
        )
    ).scalars().first()
    if (
        existing is not None
        and existing.recorder_session_id == recorder_session.id
        # ONLY while it is still recording. A phone that finished and is
        # uploading (FINALIZING, WAITING_FOR_CHUNKS) must resume that upload,
        # not abandon it, and one whose audio is already assembled has simply
        # recorded this round — reclaiming there would throw away finished work
        # to re-record over it.
        and existing.state == "RECORDING"
    ):
        # This phone's OWN recording is what is blocking it. A table that
        # reloaded mid-round with nothing yet persisted locally lands back on
        # the preflight screen, asks to start, and is told its table "already
        # recorded" this round — by itself. Nothing released it for two
        # minutes, and in orchestrated mode the round could be over by then, so
        # a dropped connection cost the table the rest of the discussion.
        #
        # The wait exists to stop a DIFFERENT device stealing a live table. It
        # has nothing to say about a phone reclaiming its own work, so this
        # goes through the same salvage path immediately: whatever it already
        # uploaded is kept and transcribed, and it records the rest.
        _release_silent_recording(session, existing, "DEVICE_REJOINED")
        # And assemble what it already sent, NOW. Unlike the silent-device
        # path, there is no backlog to wait for: the phone that owns this
        # recording is right here asking to start a new one, so what the
        # server holds is all there will ever be. Without this the uploaded
        # half sat in UPLOAD_INCOMPLETE with no transcript until somebody
        # found the manual Retry — and retention would eventually delete it.
        salvaged = salvage_total_chunks(session, existing)
        if salvaged > 0:
            existing.total_chunks = salvaged
            transition(existing, "ASSEMBLING")
            enqueue_job(session, "ASSEMBLE_AUDIO", {"recording_id": existing.id})
        existing = None
    if existing is not None and device_has_gone_silent(existing):
        # A phone that has sent nothing for minutes is not "already recording",
        # it is gone — a dead battery, most often. Blocking here left the table
        # waiting twenty minutes for the sweep, which on a thirty-minute round
        # means losing the rest of the discussion.
        #
        # Deliberately NOT assembled, unlike the organizer pressing "replace
        # device": that is a person who looked at the phone, this is a timer
        # guessing. We cannot tell a dead battery from dead WiFi, and a merely
        # disconnected phone is still recording locally — leaving this in
        # UPLOAD_INCOMPLETE lets it upload that backlog when it returns.
        _release_silent_recording(session, existing)
        existing = None
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"This table already recorded round {round_.position} "
            f"(recording is {existing.state}). Ask the facilitator if a re-recording is needed.",
        )

    recording = Recording(
        assembly_id=recorder_session.assembly_id,
        round_id=round_id,
        table_id=table.id,
        table_number=recorder_session.table_number,
        recorder_session_id=recorder_session.id,
        state="CREATED",  # column defaults only apply at flush; transition() needs it now
        mime_type=mime_type[:80],
        started_at=utcnow(),
    )
    transition(recording, "RECORDING")
    # independent assemblies never "start" a round, so this is the only signal
    # that the assembly is under way (the badge would stay Draft otherwise)
    if round_.assembly.status in ("DRAFT", "READY"):
        round_.assembly.status = "ACTIVE"
    session.add(recording)
    session.flush()
    log.info(
        "recording_started",
        recording_id=recording.id,
        round_id=round_id,
        table_number=recorder_session.table_number,
        mime_type=recording.mime_type,
    )
    return recording


def get_session_recording(
    session: Session, recorder_session: RecorderSession, recording_id: str
) -> Recording:
    recording = session.get(Recording, recording_id)
    if (
        recording is None
        or recording.assembly_id != recorder_session.assembly_id
        or recording.table_number != recorder_session.table_number
    ):
        raise HTTPException(status_code=404, detail="Recording not found")
    return recording


def receive_chunk(
    session: Session,
    recording: Recording,
    sequence_number: int,
    client_sha256: str,
    data: bytes,
) -> dict:
    """Store one chunk. Idempotent on (recording, sequence, sha256)."""
    if recording.state == "UPLOAD_INCOMPLETE":
        # we had given up on this table, and the phone came back — the whole
        # point of giving up being reversible
        transition(recording, "WAITING_FOR_CHUNKS")
        log.info("upload_resumed", recording_id=recording.id)
    elif recording.state not in ("RECORDING", "FINALIZING", "WAITING_FOR_CHUNKS"):
        raise HTTPException(status_code=409, detail=f"Recording is {recording.state}")
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty chunk")
    if len(data) > MAX_CHUNK_BYTES:
        raise HTTPException(status_code=413, detail="Chunk too large")

    actual = hashlib.sha256(data).hexdigest()
    if actual != client_sha256.lower():
        raise HTTPException(status_code=400, detail="Checksum mismatch")

    existing = session.execute(
        select(AudioChunk).where(
            AudioChunk.recording_id == recording.id,
            AudioChunk.sequence_number == sequence_number,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.sha256 == actual:
            # duplicate upload of the identical chunk: idempotent ACK
            return {"acknowledged": True, "duplicate": True, "sequence_number": sequence_number}
        raise HTTPException(status_code=409, detail="Sequence already stored with different content")

    root = get_settings().app_persistent_storage
    require_room(root, len(data), context="chunk_upload")
    directory = recording_dir(
        root, recording.assembly_id, recording.round_id, recording.table_id, recording.id
    )
    target = chunk_path(directory, sequence_number)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    session.add(
        AudioChunk(
            recording_id=recording.id,
            sequence_number=sequence_number,
            sha256=actual,
            size_bytes=len(data),
            path=str(target.relative_to(root)),
        )
    )
    recording.received_chunks = recording.received_chunks + 1
    session.flush()
    log.info(
        "recording_chunk_received",
        recording_id=recording.id,
        sequence_number=sequence_number,
        size_bytes=len(data),
    )
    return {"acknowledged": True, "duplicate": False, "sequence_number": sequence_number}


def salvage_total_chunks(session: Session, recording: Recording) -> int:
    """How much of this recording can still become audio: the contiguous
    chunk prefix starting at 0.

    Giving up on a dead phone used to enqueue assembly with whatever
    total_chunks the phone had declared — but a recording in
    WAITING_FOR_CHUNKS is there precisely BECAUSE chunks are missing, so the
    job bounced it straight back and the uploaded audio could never be used.
    A MediaRecorder stream is one container split at arbitrary byte offsets:
    the prefix is decodable, anything after a gap is not, and chunk 0 holds
    the header. Salvaging means declaring the prefix as the whole recording.
    """
    stored = {
        row
        for row in session.execute(
            select(AudioChunk.sequence_number).where(AudioChunk.recording_id == recording.id)
        ).scalars()
    }
    length = 0
    while length in stored:
        length += 1
    return length


def missing_sequences(session: Session, recording: Recording) -> list[int]:
    if recording.total_chunks is None:
        return []
    stored = {
        row
        for row in session.execute(
            select(AudioChunk.sequence_number).where(AudioChunk.recording_id == recording.id)
        ).scalars()
    }
    return [seq for seq in range(recording.total_chunks) if seq not in stored]


def complete_recording(session: Session, recording: Recording, total_chunks: int) -> dict:
    if recording.state == "RECORDING":
        transition(recording, "FINALIZING")
    elif recording.state == "UPLOAD_INCOMPLETE":
        transition(recording, "WAITING_FOR_CHUNKS")  # the phone came back
    elif recording.state not in ("FINALIZING", "WAITING_FOR_CHUNKS"):
        raise HTTPException(status_code=409, detail=f"Recording is {recording.state}")

    recording.total_chunks = total_chunks
    recording.ended_at = recording.ended_at or utcnow()
    missing = missing_sequences(session, recording)
    if missing:
        transition(recording, "WAITING_FOR_CHUNKS")
        log.info(
            "recording_waiting_for_chunks",
            recording_id=recording.id,
            missing=len(missing),
        )
        return {"state": recording.state, "missing_sequences": missing}

    transition(recording, "ASSEMBLING")
    enqueue_job(session, "ASSEMBLE_AUDIO", {"recording_id": recording.id})
    log.info("recording_completed", recording_id=recording.id, total_chunks=total_chunks)
    return {"state": recording.state, "missing_sequences": []}


def recording_status(session: Session, recording: Recording) -> dict:
    return {
        "recording_id": recording.id,
        "state": recording.state,
        "received_chunks": recording.received_chunks,
        "total_chunks": recording.total_chunks,
        "missing_sequences": missing_sequences(session, recording)
        if recording.state in ("WAITING_FOR_CHUNKS", "UPLOAD_INCOMPLETE")
        else [],
        "error_code": recording.error_code,
        "duration_seconds": recording.duration_seconds,
    }
