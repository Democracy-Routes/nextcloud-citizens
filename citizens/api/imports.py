# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organizer API: whole-file uploads, session import, attached transcripts
and audio — the way finished material gets back into the pipeline.

The routes that consume an upload do their disk work (unzipping, ffprobe)
before or outside the write transaction, and read the provider config only
after the transaction is committed, as the job handlers do: a request that
held SQLite's writer slot across an ffmpeg run or an OCS round-trip would
queue every phone's chunk upload behind it.
"""

import json
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from citizens.db.models import Recording
from citizens.db.session import get_db, get_read_db, session_scope
from citizens.logging_setup import get_logger
from citizens.security.identity import CurrentUser
from citizens.services import provider_config, uploads
from citizens.services import session_import as import_svc
from citizens.services.analysis import analysis_ready
from citizens.services.assemblies import get_owned_assembly
from citizens.services.audit import record_audit_event
from citizens.services.jobs import enqueue_job, has_live_job
from citizens.services.retranscription import queue_final_transcription
from citizens.services.table_recordings import recordings_for_table
from citizens.services.transcription import batch_transcription_ready

log = get_logger(__name__)
router = APIRouter()

DB = Annotated[Session, Depends(get_db, scope="function")]
# a read session takes no writer slot: ownership checks before disk work
ReadDB = Annotated[Session, Depends(get_read_db, scope="function")]


class UploadBegin(BaseModel):
    kind: Literal["session_export", "transcript", "audio"]
    filename: str = Field(default="", max_length=255)
    size_bytes: int = Field(gt=0)


class UploadDone(BaseModel):
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")


class MergeIn(BaseModel):
    from_number: int = Field(alias="from", ge=1, le=10000)
    into: int = Field(ge=1, le=10000)

    model_config = {"populate_by_name": True}


class ImportIn(BaseModel):
    upload_id: str = Field(min_length=36, max_length=36)
    name: str | None = Field(default=None, max_length=200)
    merge_tables: list[MergeIn] = Field(default_factory=list, max_length=200)


class AttachTranscriptIn(BaseModel):
    upload_id: str = Field(min_length=36, max_length=36)


class AttachAudioIn(BaseModel):
    upload_id: str = Field(min_length=36, max_length=36)
    mime_type: str = Field(default="audio/webm", max_length=80)


def _upload_http(exc: uploads.UploadError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.detail)


def _analysis_ready() -> bool:
    """Read after the transaction is committed; a failed config read must not
    fail the import or the attach (the material is stored), so it only
    means nothing is queued — as _maybe_enqueue_analysis does in the jobs."""
    try:
        return analysis_ready(provider_config.default_store())
    except Exception:
        log.warning("import_analysis_config_unavailable", exc_info=True)
        return False


def _transcription_ready() -> bool:
    try:
        return batch_transcription_ready(provider_config.default_store())
    except Exception:
        log.warning("import_transcription_config_unavailable", exc_info=True)
        return False


# --- uploads ----------------------------------------------------------------

@router.post("/uploads", status_code=201)
def begin_upload(data: UploadBegin, user: CurrentUser):
    try:
        meta = uploads.begin(user, data.kind, data.filename, data.size_bytes)
    except uploads.UploadError as exc:
        raise _upload_http(exc) from exc
    return {"upload_id": meta.upload_id, "part_bytes": uploads.PART_BYTES, "parts": meta.parts}


async def _read_capped_body(request: Request, limit: int = uploads.PART_BYTES) -> bytes:
    """One part at most, refused as soon as the stream passes the limit — the
    same guard the recorder's chunk route has (public_recorder.py)."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail="Part too large")
    buffer = bytearray()
    async for part in request.stream():
        buffer.extend(part)
        if len(buffer) > limit:
            raise HTTPException(status_code=413, detail="Part too large")
    return bytes(buffer)


@router.post("/uploads/{upload_id}/parts/{index}")
async def upload_part(upload_id: str, index: int, request: Request, user: CurrentUser):
    """Raw bytes, one part of PART_BYTES at most."""
    body = await _read_capped_body(request)
    try:
        return uploads.store_part(upload_id, user, index, body)
    except uploads.UploadError as exc:
        raise _upload_http(exc) from exc


@router.post("/uploads/{upload_id}/complete")
def complete_upload(upload_id: str, data: UploadDone, user: CurrentUser):
    try:
        meta = uploads.complete(upload_id, user, data.sha256)
    except uploads.UploadError as exc:
        raise _upload_http(exc) from exc
    return {"upload_id": meta.upload_id, "size_bytes": meta.size_bytes, "sha256": meta.sha256}


@router.delete("/uploads/{upload_id}", status_code=204)
def discard_upload(upload_id: str, user: CurrentUser):
    try:
        uploads.discard(upload_id, user)
    except uploads.UploadError as exc:
        raise _upload_http(exc) from exc
    return None


def _taken(upload_id: str, user: str, kind: str) -> Path:
    try:
        path, _meta = uploads.take(upload_id, user, kind)
    except uploads.UploadError as exc:
        raise _upload_http(exc) from exc
    return path


def _refused(exc: import_svc.ImportError_) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


# --- a whole session --------------------------------------------------------

@router.post("/assemblies/import", status_code=201)
def import_session(data: ImportIn, user: CurrentUser, session: DB):
    """A session export becomes a new, closed assembly of this organizer.
    Findings and the report are not copied: the tables are analysed again
    here, when a provider is configured."""
    path = _taken(data.upload_id, user, "session_export")
    merges = {m.from_number: m.into for m in data.merge_tables}
    # unzip, checksum and parse with no transaction open; the session has
    # not been used yet, so no writer slot is held while this runs
    try:
        staged = import_svc.stage_archive(path)
    except import_svc.ImportError_ as exc:
        raise _refused(exc) from exc
    try:
        result = import_svc.import_session(session, user, staged, name=data.name, merge_tables=merges)
    except import_svc.ImportError_ as exc:
        session.rollback()
        raise _refused(exc) from exc
    finally:
        staged.cleanup()
    record_audit_event(
        session, "session_imported", "assembly", result["assembly_id"], actor=user,
        data={k: result[k] for k in ("recordings", "transcripts", "audio_files")},
    )
    assembly_id = result["assembly_id"]
    # the import is safe before anything asks Nextcloud for the config
    session.commit()
    uploads.discard(data.upload_id)
    analysis = _queue_table_analyses(session, assembly_id, user)
    transcription = _queue_transcriptions(session, assembly_id, user)
    session.commit()
    return {**result, "analysis_queued": analysis, "transcription_queued": transcription}


def _queue_table_analyses(session: Session, assembly_id: str, user: str) -> bool:
    if not _analysis_ready():
        return False
    assembly = get_owned_assembly(session, assembly_id, user)
    queued = False
    for round_ in assembly.rounds:
        for table in round_.tables:
            siblings = recordings_for_table(session, round_.id, table.id)
            transcribed = [r for r in siblings if r.state == "TRANSCRIBED"]
            if not transcribed:
                continue
            primary = transcribed[-1]
            if has_live_job(session, "ANALYZE_TABLE", "recording_id", primary.id):
                continue
            enqueue_job(session, "ANALYZE_TABLE", {"recording_id": primary.id})
            queued = True
    return queued


def _queue_transcriptions(session: Session, assembly_id: str, user: str) -> bool:
    if not _transcription_ready():
        return False
    assembly = get_owned_assembly(session, assembly_id, user)
    queued = False
    for recording in session.query(Recording).filter_by(assembly_id=assembly.id, state="AUDIO_READY"):
        if queue_final_transcription(session, recording):
            queued = True
    return queued


# --- one recording ----------------------------------------------------------

def _owned_recording(session: Session, recording_id: str, user: str) -> Recording:
    recording = session.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    get_owned_assembly(session, recording.assembly_id, user)
    return recording


@router.post("/recordings/{recording_id}/transcript")
def attach_transcript(recording_id: str, data: AttachTranscriptIn, user: CurrentUser, session: DB):
    """A transcript made elsewhere becomes this recording's; the table's
    analysis runs again."""
    path = _taken(data.upload_id, user, "transcript")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail="The file is not valid JSON") from exc
    recording = _owned_recording(session, recording_id, user)
    try:
        segments = import_svc.attach_transcript(session, recording, payload)
    except import_svc.ImportError_ as exc:
        session.rollback()
        raise _refused(exc) from exc
    record_audit_event(
        session, "transcript_attached", "recording", recording.id, actor=user,
        data={"segments": segments, "table_number": recording.table_number},
    )
    session.commit()
    uploads.discard(data.upload_id)
    queued = False
    if _analysis_ready():
        recording = session.get(Recording, recording_id)
        if not has_live_job(session, "ANALYZE_TABLE", "recording_id", recording.id):
            enqueue_job(session, "ANALYZE_TABLE", {"recording_id": recording.id})
            queued = True
    session.commit()
    return {
        "recording_id": recording_id,
        "state": recording.state,
        "segments": segments,
        "duration_seconds": recording.duration_seconds,
        "transcription_queued": False,
        "analysis_queued": queued,
    }


@router.post("/recordings/{recording_id}/audio")
def attach_audio(
    recording_id: str, data: AttachAudioIn, user: CurrentUser, reader: ReadDB,
):
    """A finished audio file becomes this recording's audio; transcription
    runs as it would have after assembly."""
    path = _taken(data.upload_id, user, "audio")
    recording = _owned_recording(reader, recording_id, user)
    if recording.state not in import_svc.AUDIO_ATTACHABLE:
        raise HTTPException(
            status_code=409,
            detail=f"Audio cannot be attached while the recording is {recording.state}",
        )
    assembly_id = recording.assembly_id
    reader.close()
    # ffprobe and the remux with no session open at all
    try:
        prepared = import_svc.prepare_audio(assembly_id, recording_id, path, data.mime_type)
    except import_svc.ImportError_ as exc:
        raise _refused(exc) from exc
    with session_scope() as session:
        recording = _owned_recording(session, recording_id, user)
        try:
            import_svc.attach_audio(session, recording, prepared, data.mime_type)
        except import_svc.ImportError_ as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        record_audit_event(
            session, "audio_attached", "recording", recording.id, actor=user,
            data={"table_number": recording.table_number, "duration_seconds": prepared.duration},
        )
    uploads.discard(data.upload_id)
    queued = False
    ready = _transcription_ready()
    with session_scope() as session:
        recording = _owned_recording(session, recording_id, user)
        if ready:
            queued = queue_final_transcription(session, recording)
        state = recording.state
    return {
        "recording_id": recording_id,
        "state": state,
        "segments": None,
        "duration_seconds": prepared.duration,
        "transcription_queued": queued,
        "analysis_queued": False,
    }
