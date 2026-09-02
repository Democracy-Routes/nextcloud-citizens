# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organizer file management: audio inventory, downloads, exports, deletion."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from citizens.api.downloads import NO_STORE
from citizens.db.models import Recording
from citizens.db.models.base import utcnow
from citizens.db.session import get_db, get_read_db, session_scope
from citizens.security.identity import CurrentUser
from citizens.services import files as files_svc
from citizens.services.assemblies import get_owned_assembly
from citizens.services.audit import record_audit_event
from citizens.services.jobs import has_live_job

router = APIRouter()

DB = Annotated[Session, Depends(get_db)]
# Reads go through a session that does NOT take SQLite's single writer slot.
# Building an audio bundle copies every recording byte-for-byte and a session
# export also renders the PDF; holding the write lock across that starved every
# phone still uploading chunks, which surfaced as "database is locked" 500s
# mid-event.
ReadDB = Annotated[Session, Depends(get_read_db)]


def _refuse_if_being_assembled(session: Session, recording: Recording) -> None:
    """Deleting audio out from under a running assembly corrupts the job.

    assemble_recording commits and releases the write lock before its ffmpeg
    work, deliberately, so requests can proceed while it runs. That leaves a
    window in which this delete unlinks the very chunk files the job is about
    to read: it then fails with a missing file, retries five times, and lands
    the recording in ASSEMBLING with nothing able to free it.
    """
    if recording.state == "ASSEMBLING" or has_live_job(
        session, "ASSEMBLE_AUDIO", "recording_id", recording.id
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "This recording is being assembled right now. Wait for it to "
                "finish, then delete its audio."
            ),
        )


def _owned_recording(session: Session, recording_id: str, user: str) -> Recording:
    recording = session.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    get_owned_assembly(session, recording.assembly_id, user)
    return recording


@router.get("/assemblies/{assembly_id}/files")
def list_files(assembly_id: str, user: CurrentUser, session: ReadDB):
    assembly = get_owned_assembly(session, assembly_id, user)
    return files_svc.list_files(session, assembly)


@router.get("/recordings/{recording_id}/audio")
def download_audio(recording_id: str, user: CurrentUser, session: ReadDB):
    recording = _owned_recording(session, recording_id, user)
    path = files_svc.canonical_path(recording)
    if path is None:
        detail = (
            "The audio of this recording was deleted"
            if recording.audio_deleted_at
            else "No audio file for this recording"
        )
        raise HTTPException(status_code=404, detail=detail)
    assembly = get_owned_assembly(session, recording.assembly_id, user)
    position = next(
        (r.position for r in assembly.rounds if r.id == recording.round_id), 0
    )
    return FileResponse(
        path,
        media_type=recording.mime_type.split(";")[0] or "audio/webm",
        filename=files_svc.audio_filename(assembly, recording, position),
        # without this the proxy caches it for an hour, so deleting the audio
        # and downloading again still returns the file
        headers={"Cache-Control": NO_STORE},
    )


def _audit_after_build(event: str, assembly_id: str, user: str) -> None:
    """Record the download in its own short transaction.

    The build above runs on a read session precisely so it holds no lock; the
    audit row is the one write these endpoints need, and it must not extend
    back over the archive build.
    """
    with session_scope() as write_session:
        record_audit_event(write_session, event, "assembly", assembly_id, actor=user)


@router.get("/assemblies/{assembly_id}/audio.zip")
def download_all_audio(assembly_id: str, user: CurrentUser, session: ReadDB):
    assembly = get_owned_assembly(session, assembly_id, user)
    archive = files_svc.build_audio_zip(session, assembly)
    _audit_after_build("audio_bundle_downloaded", assembly.id, user)
    return _zip_response(archive, f"{_slug(assembly.name)}-audio.zip")


@router.get("/assemblies/{assembly_id}/export.zip")
def download_session_export(assembly_id: str, user: CurrentUser, session: ReadDB):
    assembly = get_owned_assembly(session, assembly_id, user)
    archive = files_svc.build_session_export(session, assembly)
    _audit_after_build("session_exported", assembly.id, user)
    return _zip_response(archive, f"{_slug(assembly.name)}-session-export.zip")


@router.delete("/recordings/{recording_id}/audio", status_code=200)
def delete_audio(recording_id: str, user: CurrentUser, session: DB):
    recording = _owned_recording(session, recording_id, user)
    _refuse_if_being_assembled(session, recording)
    freed = files_svc.delete_recording_audio(session, recording)
    record_audit_event(
        session, "recording_audio_deleted", "recording", recording.id, actor=user,
        data={"freed_bytes": freed, "table_number": recording.table_number},
    )
    return {"freed_bytes": freed}


@router.delete("/recordings/{recording_id}/transcript", status_code=200)
def delete_transcript(recording_id: str, user: CurrentUser, session: DB):
    recording = _owned_recording(session, recording_id, user)
    assembly = get_owned_assembly(session, recording.assembly_id, user)
    deleted = files_svc.delete_recording_transcript(session, recording)
    if deleted:
        files_svc.refresh_frozen_report(session, assembly)
        record_audit_event(
            session, "recording_transcript_deleted", "recording", recording.id, actor=user,
            data={"table_number": recording.table_number},
        )
    return {
        "deleted": deleted,
        "retranscribable": files_svc.canonical_path(recording) is not None,
    }


@router.delete("/assemblies/{assembly_id}/transcripts", status_code=200)
def delete_all_transcripts(assembly_id: str, user: CurrentUser, session: DB):
    assembly = get_owned_assembly(session, assembly_id, user)
    count = files_svc.delete_assembly_transcripts(session, assembly)
    if count:
        files_svc.refresh_frozen_report(session, assembly)
        record_audit_event(
            session, "assembly_transcripts_deleted", "assembly", assembly.id, actor=user,
            data={"transcripts": count},
        )
    return {"transcripts": count}


@router.post("/assemblies/{assembly_id}/purge-device-audio", status_code=200)
def purge_device_audio(assembly_id: str, user: CurrentUser, session: DB):
    """Ask the table phones to delete their local copies of this assembly.

    Every recording is written to the phone's own storage before it is
    uploaded, so at the end of an event each phone still holds its table's
    audio. With organisation-owned phones that is merely untidy; when citizens
    use their own, it means people walk home carrying a recording of the
    discussion without knowing it.

    The server cannot push to a phone, so this sets a flag that travels on the
    status poll each recorder already makes every few seconds. Consequences
    worth being clear about:

      * It reaches phones whose recorder is still open. One closed and carried
        out of the building never receives it — though it will act on it if
        reopened while its session is still valid. The response reports how
        many phones are known to still hold audio so the UI can say what was
        covered rather than claim completion.
      * Each phone removes only recordings the SERVER has confirmed it holds,
        so this can never destroy the last copy of anything.

    Only once the session is closed: before that the phones are still
    recording, and their local copy is the safety net the whole design rests
    on.
    """
    assembly = get_owned_assembly(session, assembly_id, user)
    if assembly.closed_at is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Close the session first. Until then each phone's local copy is "
                "the backup that protects against a failed upload."
            ),
        )
    if assembly.device_audio_purge_requested_at is None:
        assembly.device_audio_purge_requested_at = utcnow()
        session.flush()
        record_audit_event(
            session, "device_audio_purge_requested", "assembly", assembly.id, actor=user,
        )
    return {
        "requested_at": assembly.device_audio_purge_requested_at.isoformat(),
        **files_svc.device_audio_coverage(session, assembly),
    }


@router.delete("/assemblies/{assembly_id}/audio", status_code=200)
def delete_all_audio(assembly_id: str, user: CurrentUser, session: DB):
    assembly = get_owned_assembly(session, assembly_id, user)
    count, freed = files_svc.delete_assembly_audio(session, assembly)
    record_audit_event(
        session, "assembly_audio_deleted", "assembly", assembly.id, actor=user,
        data={"recordings": count, "freed_bytes": freed},
    )
    return {"recordings": count, "freed_bytes": freed}


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name)[:40].strip("-") or "assembly"


def _zip_response(archive, filename: str) -> FileResponse:
    # the archive is a throwaway build artifact: stream it, then remove it
    return FileResponse(
        archive,
        media_type="application/zip",
        filename=filename,
        headers={"Cache-Control": NO_STORE},
        background=BackgroundTask(lambda: archive.unlink(missing_ok=True)),
    )
