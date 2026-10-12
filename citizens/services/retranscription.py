# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Transcribing a recording again from its stored audio — the organizer's
Transcribe button, and every recording of an assembly whose language the
organizer changed (assemblies.change_language)."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from citizens.db.models import Recording
from citizens.services.files import canonical_path
from citizens.services.jobs import enqueue_job, has_live_job
from citizens.services.recording_states import transition

#: States a recording can be re-transcribed from. The second group is already
#: analyzed or reviewed: the state machine has always allowed them back to
#: AUDIO_READY (that is how deleting a transcript works), but the route used
#: to refuse them — so the only way to replace a poor transcript was to delete
#: it first, through a dialog warning about permanent erasure. That is the wrong
#: instrument for wanting BETTER text, and it matters now that live captions can
#: be the transcript of record.
RETRANSCRIBABLE = (
    "AUDIO_READY", "TRANSCRIBING", "TRANSCRIBED", "TRANSCRIPTION_FAILED",
    "READY_FOR_REVIEW", "REVIEWED", "ANALYSIS_FAILED",
)


def queue_final_transcription(session: Session, recording: Recording) -> bool:
    """Queue the full batch transcription of this recording's stored audio,
    whatever the Settings switches say. store_transcript replaces what is
    there and flags findings whose quotes came from the old segments, so the
    transcript need not be deleted first. False when a job is already live
    for it (nothing to stack); 409 when it cannot be done at all."""
    from citizens.jobs.handlers import TRANSCRIPTION_ATTEMPTS

    if recording.state not in RETRANSCRIBABLE:
        raise HTTPException(
            status_code=409, detail=f"Recording is {recording.state}; audio must be ready first"
        )
    if canonical_path(recording) is None:
        raise HTTPException(
            status_code=409,
            detail="This recording's audio has been deleted; it cannot be transcribed again",
        )
    # analyzed and reviewed recordings go back to plain audio first; the job
    # itself only knows how to start from there
    if recording.state in ("READY_FOR_REVIEW", "REVIEWED", "ANALYSIS_FAILED"):
        transition(recording, "AUDIO_READY")
    recording.transcript_deleted_at = None
    if has_live_job(session, "TRANSCRIBE_FINAL", "recording_id", recording.id):
        return False
    enqueue_job(
        session, "TRANSCRIBE_FINAL", {"recording_id": recording.id, "force": True},
        max_attempts=TRANSCRIPTION_ATTEMPTS,
    )
    return True
