# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organizer transcript API: fetch canonical transcripts, trigger (re)transcription."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import Recording, Transcript
from citizens.db.session import get_db
from citizens.security.identity import CurrentUser
from citizens.services.assemblies import get_owned_assembly
from citizens.services.files import canonical_path
from citizens.services.jobs import enqueue_job
from citizens.services.recording_states import transition
from citizens.services.transcription import transcript_payload

router = APIRouter()

DB = Annotated[Session, Depends(get_db)]


def _owned_recording(session: Session, recording_id: str, user: str) -> Recording:
    recording = session.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    get_owned_assembly(session, recording.assembly_id, user)  # 404 if not owned
    return recording


@router.get("/recordings/{recording_id}/transcript")
def get_transcript(recording_id: str, user: CurrentUser, session: DB):
    recording = _owned_recording(session, recording_id, user)
    transcript = session.execute(
        select(Transcript).where(Transcript.recording_id == recording.id)
    ).scalar_one_or_none()
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"No transcript yet (recording is {recording.state})")
    return transcript_payload(transcript)


#: States a recording can be re-transcribed from. The second group is already
#: analyzed or reviewed: the state machine has always allowed them back to
#: AUDIO_READY (that is how deleting a transcript works), but this endpoint used
#: to refuse them — so the only way to replace a poor transcript was to delete
#: it first, through a dialog warning about permanent erasure. That is the wrong
#: instrument for wanting BETTER text, and it matters now that live captions can
#: be the transcript of record.
RETRANSCRIBABLE = (
    "AUDIO_READY", "TRANSCRIBING", "TRANSCRIBED", "TRANSCRIPTION_FAILED",
    "READY_FOR_REVIEW", "REVIEWED", "ANALYSIS_FAILED",
)


@router.post("/recordings/{recording_id}/transcribe", status_code=202)
def request_transcription(recording_id: str, user: CurrentUser, session: DB):
    """Manual (re)transcription from the stored audio.

    Runs the full batch transcription regardless of the Settings switches, so it
    is also how an organizer upgrades a captions-derived transcript to a real
    one. store_transcript replaces what is there and flags findings whose quotes
    came from the old segments, so the transcript need not be deleted first.
    """
    recording = _owned_recording(session, recording_id, user)
    if recording.state not in RETRANSCRIBABLE:
        raise HTTPException(
            status_code=409, detail=f"Recording is {recording.state}; audio must be ready first"
        )
    if canonical_path(recording) is None:
        raise HTTPException(
            status_code=409, detail="This recording's audio has been deleted; it cannot be transcribed again"
        )
    # analyzed and reviewed recordings go back to plain audio first; the job
    # itself only knows how to start from there
    if recording.state in ("READY_FOR_REVIEW", "REVIEWED", "ANALYSIS_FAILED"):
        transition(recording, "AUDIO_READY")
    recording.transcript_deleted_at = None
    enqueue_job(session, "TRANSCRIBE_FINAL", {"recording_id": recording.id, "force": True})
    return {"queued": True, "state": recording.state}
