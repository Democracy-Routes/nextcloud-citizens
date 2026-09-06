# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Job handlers. Each runs inside its own DB session; raising retries the job."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.db.models import AppJob, Recording, Round
from citizens.db.models.base import utcnow
from citizens.logging_setup import get_logger
from citizens.providers.analysis.openai_compat import AnalysisError
from citizens.providers.transcription.base import TranscriptionError
from citizens.services import analysis as analysis_svc
from citizens.services import provider_config
from citizens.services import transcription as transcription_svc
from citizens.services.audio import (
    AudioAssemblyError,
    StorageFullError,
    assemble_recording,
    reclaim_chunks,
)
from citizens.services.jobs import enqueue_job, has_live_job
from citizens.services.recording_states import transition
from citizens.storage.paths import live_caption_path

log = get_logger(__name__)


class PermanentJobError(Exception):
    """Raised when retrying cannot help; the job goes straight to FAILED."""


def _commit_failure_state(session: Session) -> None:
    """Persist a recording's error state before re-raising.

    The runner rolls the session back on a temporary failure before scheduling
    the retry (citizens/jobs/runner.py). Without this commit the state set just
    above is discarded, and when attempts finally run out the job goes FAILED
    while the recording stays in TRANSCRIBING/ANALYZING forever — an "in
    progress" pill for work nothing is doing.
    """
    try:
        session.commit()
    except Exception:
        # the retry itself matters more than the bookkeeping
        session.rollback()
        log.warning("failure_state_commit_failed", exc_info=True)


def handle_assemble_audio(session: Session, payload: dict) -> None:
    recording = session.get(Recording, payload["recording_id"])
    if recording is None:
        raise PermanentJobError(f"Recording {payload['recording_id']} no longer exists")
    if recording.state == "AUDIO_READY":
        # Already assembled — this is a retry. The retry may exist precisely
        # because the enqueue after success failed, so repair that rather than
        # skipping it.
        _maybe_enqueue_transcription(session, recording)
        return
    if recording.state != "ASSEMBLING":
        transition(recording, "ASSEMBLING")
    try:
        redundant_chunks = assemble_recording(session, recording)
    except StorageFullError:
        recording.error_code = "STORAGE_FULL"
        _commit_failure_state(session)
        log.error("audio_assembly_deferred_no_space", recording_id=recording.id)
        raise  # retryable: the chunks are safe and space may be freed
    except AudioAssemblyError as exc:
        recording.error_code = exc.code
        transition(recording, "AUDIO_INVALID")
        log.error("audio_assembly_failed", recording_id=recording.id, error_code=exc.code)
        raise PermanentJobError(str(exc)) from exc

    # Commit AUDIO_READY BEFORE reclaiming the chunk files. Reclaiming unlinks
    # the bytes and deletes the rows; if this commit failed afterwards, the
    # rollback would restore rows pointing at files that no longer exist and
    # every retry would then fail permanently. A full disk — exactly what
    # brings us here — makes that a real sequence, not a theoretical one.
    session.commit()
    reclaim_chunks(session, recording, redundant_chunks)

    _maybe_enqueue_transcription(session, recording)


def _maybe_enqueue_transcription(session: Session, recording: Recording) -> None:
    """Queue the next stage after assembly.

    Failing to read the config here must NOT fail the assembly — the audio is
    safely AUDIO_READY and re-running assembly would be pointless work. But a
    swallowed failure used to leave the recording in AUDIO_READY forever with
    nothing queued, a green pill blocking the round's analysis, because nothing
    else ever enqueued transcription. So: log loudly, and let
    sweep_missed_enqueues() be the backstop that retries when Nextcloud is
    reachable again.
    """
    recording_id = recording.id
    # Release the writer slot BEFORE the OCS round-trips: these are HTTPS calls
    # to Nextcloud, and holding the write transaction across them queued every
    # concurrent chunk upload behind busy_timeout (runner.py's contract).
    session.commit()
    try:
        store = provider_config.default_store()
        batch = transcription_svc.batch_transcription_ready(store)
        live = transcription_svc.live_transcription_ready(store)
    except Exception:
        log.warning(
            "transcription_enqueue_deferred", recording_id=recording_id, exc_info=True
        )
        return
    if batch and not has_live_job(session, "TRANSCRIBE_FINAL", "recording_id", recording_id):
        enqueue_job(session, "TRANSCRIBE_FINAL", {"recording_id": recording_id})
        log.info("transcription_enqueued", recording_id=recording_id)
    elif live and not has_live_job(session, "TRANSCRIBE_FROM_LIVE", "recording_id", recording_id):
        # captions are the only transcript this assembly will get, so they
        # become the record rather than being discarded with the session
        enqueue_job(session, "TRANSCRIBE_FROM_LIVE", {"recording_id": recording_id})
        log.info("live_transcription_enqueued", recording_id=recording_id)


def handle_transcribe_final(session: Session, payload: dict) -> None:
    recording = session.get(Recording, payload["recording_id"])
    if recording is None:
        raise PermanentJobError(f"Recording {payload['recording_id']} no longer exists")
    if recording.state == "TRANSCRIBED" and not payload.get("force"):
        _maybe_enqueue_analysis(session, recording)
        return
    if recording.state in ("AUDIO_READY", "TRANSCRIPTION_FAILED", "TRANSCRIBED"):
        transition(recording, "TRANSCRIBING")
    elif recording.state != "TRANSCRIBING":
        raise PermanentJobError(f"Recording is {recording.state}; cannot transcribe")

    # persist TRANSCRIBING and release the writer slot before the OCS reads
    # inside default_store()/transcribe_recording — holding it across HTTPS
    # round-trips is the lock-starvation regression this codebase has fixed
    # three times (runner.py's contract)
    session.commit()
    store = provider_config.default_store()
    try:
        transcription_svc.transcribe_recording(session, store, recording)
    except TranscriptionError as exc:
        recording.error_code = "TRANSCRIPTION_FAILED"
        transition(recording, "TRANSCRIPTION_FAILED")
        _commit_failure_state(session)
        log.error("stt_failed", recording_id=recording.id, permanent=exc.permanent)
        if exc.permanent:
            raise PermanentJobError(str(exc)) from exc
        raise  # temporary (429/5xx/network) → job retry with backoff
    recording.error_code = ""
    transition(recording, "TRANSCRIBED")
    _maybe_enqueue_analysis(session, recording)


# A caption session finishes draining within seconds of the round ending, but
# the assembly job can beat it there. Retries cover the gap (attempts land at
# roughly 0, 30, 90, 210 and 450 s); past this the captions are not coming.
LIVE_CAPTIONS_GRACE_SECONDS = 300


def handle_transcribe_from_live(session: Session, payload: dict) -> None:
    """Make the round's live captions the transcript of record.

    Only reached when an administrator has turned final transcription off. The
    result is a real Transcript with segments, so analysis, evidence citations
    and the report work exactly as they do for a batch transcript — flagged
    source="live" so a reader can tell.
    """
    recording = session.get(Recording, payload["recording_id"])
    if recording is None:
        raise PermanentJobError(f"Recording {payload['recording_id']} no longer exists")
    if recording.state == "TRANSCRIBED" and not payload.get("force"):
        _maybe_enqueue_analysis(session, recording)
        return
    if recording.state in ("AUDIO_READY", "TRANSCRIPTION_FAILED", "TRANSCRIBED"):
        transition(recording, "TRANSCRIBING")
    elif recording.state != "TRANSCRIBING":
        raise PermanentJobError(f"Recording is {recording.state}; cannot transcribe")

    path = live_caption_path(
        get_settings().app_persistent_storage, recording.assembly_id, recording.id
    )
    if not path.exists():
        waited = (utcnow() - recording.updated_at).total_seconds()
        if waited < LIVE_CAPTIONS_GRACE_SECONDS:
            # a plain exception is retried with backoff; the rollback undoes
            # the TRANSCRIBING transition above, so the next attempt starts clean
            raise RuntimeError("Live captions have not been written yet")
        _fail_transcription(session, recording, "LIVE_CAPTIONS_MISSING")
        raise PermanentJobError("The caption session never wrote a transcript")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _fail_transcription(session, recording, "LIVE_CAPTIONS_UNREADABLE")
        raise PermanentJobError(f"Live captions unreadable: {exc}") from exc

    normalized = transcription_svc.transcript_from_live_captions(data)
    if not normalized.segments:
        # the engine never connected, or heard nothing it was confident about.
        # Saying so beats leaving a table silently absent from the report.
        _fail_transcription(session, recording, "LIVE_CAPTIONS_EMPTY")
        raise PermanentJobError("Live captions produced no text")

    transcription_svc.store_transcript(session, recording, normalized, source="live")
    recording.error_code = ""
    transition(recording, "TRANSCRIBED")
    log.info(
        "live_transcript_stored",
        recording_id=recording.id,
        segments=len(normalized.segments),
        truncated=bool(data.get("truncated")),
    )
    _maybe_enqueue_analysis(session, recording)


def _fail_transcription(session: Session, recording: Recording, code: str) -> None:
    recording.error_code = code
    transition(recording, "TRANSCRIPTION_FAILED")
    log.error("live_transcription_failed", recording_id=recording.id, error_code=code)


#: A table with a recording in one of these still has audio on its way to a
#: transcript, so analysing the table now would analyse half of it.
TABLE_PENDING_STATES = {
    "CREATED", "RECORDING", "FINALIZING", "WAITING_FOR_CHUNKS", "ASSEMBLING",
    "AUDIO_READY", "TRANSCRIBING",
}


def _table_still_transcribing(session: Session, recording: Recording) -> bool:
    """Is another recording of this same table still on its way to a transcript?

    A table whose phone was replaced has two recordings of one discussion.
    Analysis covers the table as a whole, so it must wait for both halves —
    otherwise the first to finish transcribing is analysed on its own and the
    rest of the round is missing from the summary and the findings.
    """
    states = session.execute(
        select(Recording.state).where(
            Recording.round_id == recording.round_id,
            Recording.table_id == recording.table_id,
            Recording.id != recording.id,
        )
    ).scalars()
    return any(state in TABLE_PENDING_STATES for state in states)


def _maybe_enqueue_analysis(session: Session, recording: Recording) -> None:
    """Same contract as _maybe_enqueue_transcription: a failed config read is
    logged and left to the sweep, never fatal to the transcription job."""
    recording_id = recording.id
    if _table_still_transcribing(session, recording):
        log.info("analysis_waiting_for_sibling", recording_id=recording_id)
        return
    # commit before the OCS round-trips — see _maybe_enqueue_transcription
    session.commit()
    try:
        ready = analysis_svc.analysis_ready(provider_config.default_store())
    except Exception:
        log.warning("analysis_enqueue_deferred", recording_id=recording_id, exc_info=True)
        return
    if ready and not has_live_job(session, "ANALYZE_TABLE", "recording_id", recording_id):
        enqueue_job(session, "ANALYZE_TABLE", {"recording_id": recording_id})
        log.info("analysis_enqueued", recording_id=recording_id)


def handle_analyze_table(session: Session, payload: dict) -> None:
    recording = session.get(Recording, payload["recording_id"])
    if recording is None:
        raise PermanentJobError(f"Recording {payload['recording_id']} no longer exists")
    if recording.state == "READY_FOR_REVIEW" and not payload.get("force"):
        return
    if recording.state in ("TRANSCRIBED", "ANALYSIS_FAILED", "READY_FOR_REVIEW"):
        transition(recording, "ANALYZING")
    elif recording.state != "ANALYZING":
        raise PermanentJobError(f"Recording is {recording.state}; cannot analyze")

    # commit before the OCS reads — see handle_transcribe_final
    session.commit()
    store = provider_config.default_store()
    try:
        analysis_svc.analyze_table(session, store, recording)
    except AnalysisError as exc:
        recording.error_code = "ANALYSIS_FAILED"
        transition(recording, "ANALYSIS_FAILED")
        _commit_failure_state(session)
        log.error("analysis_failed", recording_id=recording.id, permanent=exc.permanent)
        if exc.permanent:
            raise PermanentJobError(str(exc)) from exc
        raise
    recording.error_code = ""
    transition(recording, "READY_FOR_REVIEW")
    # The analysis covered the whole TABLE — both halves of a replaced-device
    # round — but only the recording named in the payload was transitioned.
    # When the superseded half transcribed last, the job ran under ITS id, the
    # live half stayed TRANSCRIBED (a pending state), and the round's
    # cross-table analysis never ran until close or a manual re-run.
    for sibling in analysis_svc.table_recordings(session, recording):
        if sibling.id != recording.id and sibling.state == "TRANSCRIBED":
            transition(sibling, "ANALYZING")
            transition(sibling, "READY_FOR_REVIEW")
    maybe_enqueue_round_analysis(session, recording)


def maybe_enqueue_round_analysis(session: Session, recording: Recording) -> None:
    """When the last analyzed table of the round is done, cluster cross-table."""
    states = [
        row
        for row in session.execute(
            select(Recording.state).where(Recording.round_id == recording.round_id)
        ).scalars()
    ]
    healthy_pending = {
        "CREATED", "RECORDING", "FINALIZING", "WAITING_FOR_CHUNKS", "ASSEMBLING",
        "AUDIO_READY", "TRANSCRIBING", "TRANSCRIBED", "ANALYZING",
    }
    if any(state in healthy_pending for state in states):
        return
    payload = json.dumps({"round_id": recording.round_id})
    already = session.execute(
        select(AppJob).where(
            AppJob.type == "ANALYZE_ROUND",
            AppJob.state.in_(("QUEUED", "RUNNING", "RETRY")),
            AppJob.payload_json == payload,
        )
    ).scalar_one_or_none()
    if already is None:
        enqueue_job(session, "ANALYZE_ROUND", {"round_id": recording.round_id})
        log.info("round_analysis_enqueued", round_id=recording.round_id)


def _refresh_frozen_report_if_closed(session: Session, round_) -> None:
    """close_assembly enqueues this round's final analysis and freezes the
    report IN THE SAME TRANSACTION — so the snapshot participants read was
    taken before the summaries it was waiting for could exist. When the
    analysis lands after the close, the frozen copy catches up here."""
    assembly = round_.assembly
    if assembly is None or assembly.closed_at is None:
        return
    from citizens.services.lifecycle import snapshot_final_report

    snapshot_final_report(session, assembly)
    log.info("frozen_report_refreshed_after_analysis", assembly_id=assembly.id)


def handle_analyze_round(session: Session, payload: dict) -> None:
    round_ = session.get(Round, payload["round_id"])
    if round_ is None:
        raise PermanentJobError(f"Round {payload['round_id']} no longer exists")
    # even a bare read opened BEGIN IMMEDIATE — commit before the OCS reads
    session.commit()
    store = provider_config.default_store()
    try:
        analysis_svc.analyze_round(session, store, round_)
    except AnalysisError as exc:
        log.error("analysis_failed", round_id=round_.id, permanent=exc.permanent)
        if exc.permanent:
            raise PermanentJobError(str(exc)) from exc
        raise
    if round_.status in ("ENDED", "PROCESSING"):
        round_.status = "READY_FOR_REVIEW"
    _refresh_frozen_report_if_closed(session, round_)


HANDLERS = {
    "ASSEMBLE_AUDIO": handle_assemble_audio,
    "TRANSCRIBE_FINAL": handle_transcribe_final,
    "TRANSCRIBE_FROM_LIVE": handle_transcribe_from_live,
    "ANALYZE_TABLE": handle_analyze_table,
    "ANALYZE_ROUND": handle_analyze_round,
}
