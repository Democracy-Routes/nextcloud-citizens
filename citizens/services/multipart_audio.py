# SPDX-License-Identifier: AGPL-3.0-or-later
"""Durable bounded-size transport for an immutable MediaRecorder chunk."""
import hashlib
import os
import tempfile
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.db.models import Recording
from citizens.db.models.base import utcnow
from citizens.db.models.recording import AudioChunk, AudioPart
from citizens.services.recording_states import transition
from citizens.storage.durable import sync_directory, write_audio
from citizens.storage.paths import chunk_path, recording_dir
from citizens.storage.space import require_room

PART_BYTES = 1024 * 1024


def _directory(recording):
    return recording_dir(get_settings().app_persistent_storage, recording.assembly_id,
                         recording.round_id, recording.table_id, recording.id)


def _accepting(recording):
    if recording.audio_deleted_at is not None or recording.state not in (
        "RECORDING", "FINALIZING", "WAITING_FOR_CHUNKS", "UPLOAD_INCOMPLETE"
    ):
        raise HTTPException(409, "Recording no longer accepts audio; keep the local copy")
    if recording.state == "UPLOAD_INCOMPLETE":
        transition(recording, "WAITING_FOR_CHUNKS")


def _parts(session, recording_id, sequence):
    return list(session.scalars(select(AudioPart).where(
        AudioPart.recording_id == recording_id, AudioPart.sequence_number == sequence
    ).order_by(AudioPart.part_number)))


def part_status(session: Session, recording: Recording, sequence: int):
    chunk = session.scalar(select(AudioChunk).where(
        AudioChunk.recording_id == recording.id, AudioChunk.sequence_number == sequence
    ))
    parts = _parts(session, recording.id, sequence)
    return {
        "part_bytes": PART_BYTES,
        "chunk_sha256": chunk.sha256 if chunk else (parts[0].chunk_sha256 if parts else None),
        "total_bytes": chunk.size_bytes if chunk else (parts[0].total_bytes if parts else None),
        "complete": chunk is not None,
        "parts": [{"number": p.part_number, "sha256": p.sha256} for p in parts],
    }


def receive_part(session, recording, sequence, number, total_bytes, chunk_hash, part_hash, data):
    _accepting(recording)
    expected = min(PART_BYTES, total_bytes - number * PART_BYTES)
    if expected <= 0 or len(data) != expected:
        raise HTTPException(422, "Part size does not match its position")
    if hashlib.sha256(data).hexdigest() != part_hash:
        raise HTTPException(400, "Part checksum mismatch")
    parts = _parts(session, recording.id, sequence)
    if parts and (parts[0].total_bytes != total_bytes or parts[0].chunk_sha256 != chunk_hash):
        raise HTTPException(409, "Chunk metadata conflicts with stored parts")
    existing = next((p for p in parts if p.part_number == number), None)
    if existing and existing.sha256 != part_hash:
        raise HTTPException(409, "Part already stored with different content")
    root = get_settings().app_persistent_storage
    target = _directory(recording) / "parts" / str(sequence) / f"{number}.bin"
    require_room(root, len(data), context="audio_part")
    # A duplicate repairs a file lost after its database receipt was committed.
    write_audio(target, data)
    if existing is None:
        session.add(AudioPart(
            recording_id=recording.id, sequence_number=sequence, part_number=number,
            total_bytes=total_bytes, chunk_sha256=chunk_hash, sha256=part_hash,
            size_bytes=len(data), path=str(target.relative_to(root)),
        ))
    recording.updated_at = utcnow()
    session.commit()
    return {"acknowledged": True}


def finalize_chunk(session: Session, recording: Recording, sequence: int):
    _accepting(recording)
    existing = session.scalar(select(AudioChunk).where(
        AudioChunk.recording_id == recording.id, AudioChunk.sequence_number == sequence
    ))
    if existing is not None:
        return {"acknowledged": True, "duplicate": True,
                "sha256": existing.sha256, "size_bytes": existing.size_bytes}
    parts = _parts(session, recording.id, sequence)
    if not parts:
        raise HTTPException(409, "No parts received")
    total = parts[0].total_bytes
    count = (total + PART_BYTES - 1) // PART_BYTES
    if len(parts) != count or any(p.part_number != i for i, p in enumerate(parts)):
        raise HTTPException(409, "Missing parts; resume the upload")
    root = get_settings().app_persistent_storage
    require_room(root, total, context="audio_part_assembly")
    target = chunk_path(_directory(recording), sequence)
    target.parent.mkdir(parents=True, exist_ok=True)
    session.commit()  # no writer lock while copying or hashing a large chunk
    digest = hashlib.sha256()
    size = 0
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as out:
        temporary = Path(out.name)
        try:
            for part in parts:
                try:
                    data = (root / part.path).read_bytes()  # bounded to 1 MiB
                except FileNotFoundError as exc:
                    raise HTTPException(409, "Stored part is missing; resend it") from exc
                if len(data) != part.size_bytes or hashlib.sha256(data).hexdigest() != part.sha256:
                    raise HTTPException(409, "Stored part is damaged; resend it")
                out.write(data)
                digest.update(data)
                size += len(data)
            if size != total or digest.hexdigest() != parts[0].chunk_sha256:
                raise HTTPException(400, "Whole chunk checksum mismatch")
            out.flush()
            os.fsync(out.fileno())
            session.refresh(recording)
            _accepting(recording)
            existing = session.scalar(select(AudioChunk).where(
                AudioChunk.recording_id == recording.id, AudioChunk.sequence_number == sequence
            ))
            if existing is None:
                os.replace(temporary, target)
                sync_directory(target.parent)
                session.add(AudioChunk(recording_id=recording.id, sequence_number=sequence,
                                       sha256=digest.hexdigest(), size_bytes=size,
                                       path=str(target.relative_to(root))))
                recording.received_chunks += 1
                recording.updated_at = utcnow()
            elif existing.sha256 != digest.hexdigest():
                raise HTTPException(409, "Chunk already stored with different content")
            session.commit()
        finally:
            temporary.unlink(missing_ok=True)
    return {"acknowledged": True, "duplicate": existing is not None,
            "sha256": digest.hexdigest(), "size_bytes": size}
