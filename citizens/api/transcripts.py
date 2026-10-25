# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organizer transcript API: fetch canonical transcripts, trigger (re)transcription."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.db.models import Recording, Transcript
from citizens.db.session import get_db
from citizens.security.identity import CurrentUser
from citizens.services.assemblies import get_owned_assembly
from citizens.services.retranscription import RETRANSCRIBABLE, queue_final_transcription
from citizens.services.table_recordings import recording_slots, slot_label
from citizens.services.transcription import transcript_payload
from citizens.storage.paths import live_caption_path

router = APIRouter()

__all__ = ["RETRANSCRIBABLE", "router"]

DB = Annotated[Session, Depends(get_db, scope="function")]


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
    payload = transcript_payload(transcript)
    # which of the table's phones made the audio, and whether the round's live
    # captions also exist on disk as the provisional record they were
    slot = recording_slots(session, [recording]).get(recording.id, 1)
    payload["provenance"].update(
        recorder_slot=slot,
        recorder_label=slot_label(slot),
        live_captions_available=live_caption_path(
            get_settings().app_persistent_storage, recording.assembly_id, recording.id
        ).exists(),
    )
    return payload


@router.post("/recordings/{recording_id}/transcribe", status_code=202)
def request_transcription(recording_id: str, user: CurrentUser, session: DB):
    """Manual (re)transcription from the stored audio.

    Runs the full batch transcription regardless of the Settings switches, so it
    is also how an organizer upgrades a captions-derived transcript to a real
    one. store_transcript replaces what is there and flags findings whose quotes
    came from the old segments, so the transcript need not be deleted first.
    """
    recording = _owned_recording(session, recording_id, user)
    queue_final_transcription(session, recording)
    return {"queued": True, "state": recording.state}
