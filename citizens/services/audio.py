# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Audio assembly and validation (brief §23).

Chunks from one continuous MediaRecorder session concatenate into a valid
stream; ffmpeg then remuxes it into a clean container (fixing metadata like
missing duration) without re-encoding.
"""

import hashlib
import json
import subprocess

from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.db.models import Recording
from citizens.logging_setup import get_logger
from citizens.services.recording import missing_sequences
from citizens.services.recording_states import transition
from citizens.storage.paths import assembled_dir, recording_dir, temp_dir
from citizens.storage.space import has_room_for

log = get_logger(__name__)

EXTENSION_BY_MIME = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
}


class AudioAssemblyError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class StorageFullError(Exception):
    """Not enough disk to assemble safely. Retryable — the audio is fine and
    the operator may free space, so this must never mark it AUDIO_INVALID."""


def _extension_for(mime_type: str) -> str:
    base = mime_type.split(";")[0].strip().lower()
    return EXTENSION_BY_MIME.get(base, ".webm")


def assemble_recording(session: Session, recording: Recording) -> list | None:
    """Concatenate chunks, validate with ffprobe, remux, checksum, mark AUDIO_READY.

    Returns the chunk rows that are now redundant, for the caller to reclaim
    with reclaim_chunks() once AUDIO_READY has been committed — or None when
    there was nothing to assemble. See the comment at the end of the body.
    """
    missing = missing_sequences(session, recording)
    if missing:
        transition(recording, "WAITING_FOR_CHUNKS")
        log.warning("audio_assemble_missing_chunks", recording_id=recording.id, missing=len(missing))
        return None

    root = get_settings().app_persistent_storage
    directory = recording_dir(
        root, recording.assembly_id, recording.round_id, recording.table_id, recording.id
    )
    extension = _extension_for(recording.mime_type)
    raw_path = temp_dir(root) / f"{recording.id}-raw{extension}"
    canonical = assembled_dir(root, recording.assembly_id) / f"{recording.id}{extension}"
    canonical.parent.mkdir(parents=True, exist_ok=True)

    chunks = sorted(recording.chunks, key=lambda c: c.sequence_number)
    # Only up to the declared total. A salvaged recording (dead phone, chunk
    # lost to a full disk) deliberately truncates total_chunks to the
    # contiguous prefix — but rows past the gap may still be stored, and a
    # MediaRecorder stream concatenated across a gap is not decodable audio.
    if recording.total_chunks is not None:
        chunks = [c for c in chunks if c.sequence_number < recording.total_chunks]
    # assembly writes a full raw concat plus the remuxed copy, so it needs
    # roughly twice the recording free before it starts
    needed = sum(chunk.size_bytes for chunk in chunks) * 2
    if not has_room_for(root, needed):
        # deliberately NOT an AudioAssemblyError: that marks the recording
        # AUDIO_INVALID for good, and there is nothing wrong with this audio.
        # Space may be freed, so let the job back off and try again.
        raise StorageFullError(
            "Not enough free storage to assemble this recording — the uploaded chunks are kept"
        )
    # release the DB write lock before file/ffmpeg work: the job session
    # otherwise holds SQLite's single writer slot for the whole assembly,
    # 500-ing every API request after busy_timeout (expire_on_commit=False
    # keeps the loaded chunk rows usable)
    session.commit()
    # The commit above deliberately releases the write lock before the ffmpeg
    # work, which leaves a window in which the organizer can delete this
    # recording's audio. Deleting mid-assembly is refused now, but the check
    # costs nothing and closes the race rather than narrowing it.
    if recording.audio_deleted_at is not None:
        raise AudioAssemblyError(
            "AUDIO_DELETED", "The audio of this recording was deleted while it was assembling"
        )
    digest = hashlib.sha256()
    with open(raw_path, "wb") as raw:
        for chunk in chunks:
            try:
                data = (root / chunk.path).read_bytes()
            except FileNotFoundError as exc:
                # Not a transient fault: the bytes are gone, so retrying can
                # only fail the same way five times and then strand the
                # recording in ASSEMBLING with nothing able to free it.
                raw_path.unlink(missing_ok=True)
                raise AudioAssemblyError(
                    "CHUNKS_GONE",
                    f"Chunk {chunk.sequence_number} is missing from storage",
                ) from exc
            if hashlib.sha256(data).hexdigest() != chunk.sha256:
                raw_path.unlink(missing_ok=True)
                raise AudioAssemblyError(
                    "CHUNK_CORRUPTED", f"Chunk {chunk.sequence_number} failed checksum on disk"
                )
            raw.write(data)
            digest.update(data)

    try:
        probe = _ffprobe(raw_path)
        _remux(raw_path, canonical)
        final_probe = _ffprobe(canonical)
    except AudioAssemblyError:
        raise
    finally:
        raw_path.unlink(missing_ok=True)

    recording.canonical_audio_path = str(canonical.relative_to(root))
    recording.duration_seconds = final_probe.get("duration") or probe.get("duration")
    recording.sha256 = hashlib.sha256(canonical.read_bytes()).hexdigest()
    recording.error_code = ""
    transition(recording, "AUDIO_READY")
    log.info(
        "audio_assembled",
        recording_id=recording.id,
        duration_seconds=recording.duration_seconds,
        size_bytes=canonical.stat().st_size,
    )
    _write_manifest(directory, recording, chunks)
    # NOT discarded here. _discard_chunks unlinks files and deletes rows; if
    # the commit that records AUDIO_READY then fails (a full disk is a modeled
    # condition on this path), the rollback restores AudioChunk rows pointing
    # at files that no longer exist, and every retry fails permanently. The
    # caller reclaims them once the new state is durable.
    return chunks


def reclaim_chunks(session: Session, recording: Recording, chunks) -> None:
    """Reclaim the per-chunk copies of an assembled recording.

    Separate from assemble_recording, and called only after AUDIO_READY is
    committed, so a failed commit can never leave rows rolled back while their
    files are already unlinked.
    """
    if not chunks:
        return
    root = get_settings().app_persistent_storage
    directory = recording_dir(
        root, recording.assembly_id, recording.round_id, recording.table_id, recording.id
    )
    _discard_chunks(session, root, directory, recording, chunks)


def _discard_chunks(session: Session, root, directory, recording: Recording, chunks) -> None:
    """Drop the per-chunk copies now that the canonical file is verified.

    Chunks are the upload transport, not a second archive, but nothing ever
    collected them — so every recording sat on disk twice, permanently
    (measured on a test instance: 37 MB of chunks against 35 MB of assembled
    audio). manifest.json keeps each chunk's sequence, checksum and size, so
    the audit trail survives the bytes.

    Safe here specifically: ffprobe has validated the remuxed file, its
    checksum is stored, and no state transitions back into ASSEMBLING once a
    recording is AUDIO_READY.
    """
    removed, freed = [], 0
    for chunk in chunks:
        try:
            (root / chunk.path).unlink(missing_ok=True)
        except OSError:
            log.warning("chunk_cleanup_failed", recording_id=recording.id, exc_info=True)
            continue  # leave the row while the bytes are still on disk
        removed.append(chunk)
        freed += chunk.size_bytes
    for chunk in removed:
        # re-fetch: a concurrent delete of this recording's audio may already
        # have removed the row, and deleting a stale one raises StaleDataError
        # on flush and fails the whole job
        live = session.get(type(chunk), chunk.id)
        if live is not None:
            session.delete(live)
    chunks_dir = directory / "chunks"
    if chunks_dir.is_dir():
        try:
            chunks_dir.rmdir()  # keep manifest.json beside it
        except OSError:
            pass
    log.info("chunks_reclaimed", recording_id=recording.id, chunks=len(removed), freed_bytes=freed)


def _write_manifest(directory, recording: Recording, chunks) -> None:
    manifest = {
        "recording_id": recording.id,
        "mime_type": recording.mime_type,
        "total_chunks": recording.total_chunks,
        "canonical_audio_path": recording.canonical_audio_path,
        "sha256": recording.sha256,
        "duration_seconds": recording.duration_seconds,
        "chunks": [
            {"sequence": c.sequence_number, "sha256": c.sha256, "size": c.size_bytes} for c in chunks
        ],
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=1))


def _ffprobe(path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise AudioAssemblyError("AUDIO_INVALID", f"ffprobe failed: {result.stderr[-500:]}")
    info = json.loads(result.stdout or "{}")
    streams = info.get("streams", [])
    if not any(s.get("codec_type") == "audio" for s in streams):
        raise AudioAssemblyError("AUDIO_INVALID", "No audio stream found")
    duration = info.get("format", {}).get("duration")
    return {"duration": float(duration) if duration else None}


def _remux(source, target) -> None:
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-c", "copy", str(target)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        target.unlink(missing_ok=True)
        raise AudioAssemblyError("AUDIO_INVALID", f"ffmpeg remux failed: {result.stderr[-500:]}")
