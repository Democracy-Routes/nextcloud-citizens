# SPDX-License-Identifier: AGPL-3.0-or-later
"""Durable bounded-size transport for an immutable MediaRecorder chunk."""
import hashlib
import os
import tempfile
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.db.models import Recording
from citizens.db.models.base import utcnow
from citizens.db.models.recording import AudioChunk, AudioPart
from citizens.logging_setup import get_logger
from citizens.services.recording_states import transition
from citizens.storage.durable import sync_directory, write_audio
from citizens.storage.paths import chunk_path, recording_dir
from citizens.storage.space import require_room

log = get_logger(__name__)

PART_BYTES = 1024 * 1024

#: Upper bound on what one sequence may declare as its total. A chunk the
#: plain route (public_recorder._read_capped_body) refuses above 5 MiB does
#: not become 16 GiB of "expected parts" by going through the parts routes:
#: without a bound, a wrong X-Total-Bytes stored against the first part makes
#: finalize compute a part count that can never arrive, and every honest
#: retry then hits "Chunk metadata conflicts with stored parts" — the
#: sequence is bricked, recoverable only by deleting the audio server-side.
#: Generous above real chunks (a round's audio is minutes, not hours) while
#: keeping a garbage declaration cheap to reject.
MAX_DECLARED_CHUNK_BYTES = 64 * 1024 * 1024


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
    if not 0 < total_bytes <= MAX_DECLARED_CHUNK_BYTES:
        # rejected BEFORE anything is stored, so a correct retry is a clean
        # first upload rather than a conflict with its own poisoned metadata
        raise HTTPException(422, "Declared chunk size is out of range")
    if number * PART_BYTES >= total_bytes:
        raise HTTPException(422, "Part number beyond the declared chunk size")
    expected = min(PART_BYTES, total_bytes - number * PART_BYTES)
    if expected <= 0 or len(data) != expected:
        raise HTTPException(422, "Part size does not match its position")
    if hashlib.sha256(data).hexdigest() != part_hash:
        raise HTTPException(400, "Part checksum mismatch")
    # One sequence, one set of bytes. The plain route stores the same sequence
    # as an AudioChunk; without the check both directions exist, a chunk and
    # parts could describe different content for it — part_status would then
    # report the chunk's hash against bytes the parts assembled from, and a
    # resuming phone reads "corruption" in bytes the server itself mixed.
    chunk = session.scalar(select(AudioChunk).where(
        AudioChunk.recording_id == recording.id, AudioChunk.sequence_number == sequence
    ))
    if chunk is not None and chunk.sha256 != chunk_hash:
        raise HTTPException(409, "Chunk already stored with different content")
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
    # duplicate: the route feeds live captions only for a part it has not seen
    # — a retry (lost ack, or the client's force-resend after a finalize
    # conflict) must not push the same audio into the caption stream twice
    return {"acknowledged": True, "duplicate": existing is not None}


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
    recording_id_for_log = recording.id
    target = chunk_path(_directory(recording), sequence)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Copy what the loop below needs into plain values, then commit — NO lock
    # at all while copying: this handler's own session is SQLite's one writer,
    # and a reader snapshot can serve the status polls that pile up behind a
    # slow copy. (expire_on_commit is False, so the rows would survive the
    # commit anyway; the copies just make the unlocked section self-contained.)
    part_files = [
        (part.part_number, root / part.path, part.sha256, part.size_bytes) for part in parts
    ]
    chunk_sha256 = parts[0].chunk_sha256
    session.commit()
    digest = hashlib.sha256()
    size = 0
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as out:
        temporary = Path(out.name)
        try:
            for _, part_file, part_sha256, part_size in part_files:
                try:
                    data = part_file.read_bytes()  # bounded to 1 MiB
                except FileNotFoundError as exc:
                    raise HTTPException(409, "Stored part is missing; resend it") from exc
                if len(data) != part_size or hashlib.sha256(data).hexdigest() != part_sha256:
                    raise HTTPException(409, "Stored part is damaged; resend it")
                out.write(data)
                digest.update(data)
                size += len(data)
            if size != total or digest.hexdigest() != chunk_sha256:
                raise HTTPException(400, "Whole chunk checksum mismatch")
            out.flush()
            os.fsync(out.fileno())
            # Re-read the recording before trusting it. The copy above ran with
            # no lock and expire_on_commit is False, so `recording` still holds
            # the snapshot from before it: in the meantime the sweep can have
            # marked it UPLOAD_INCOMPLETE, /complete moved it to ASSEMBLING,
            # or the audio been deleted — and received_chunks below must add
            # to the CURRENT count, or two concurrent finalizes of different
            # sequences clobber each other's increment (SQLAlchemy writes an
            # absolute SET, not an increment). The refresh opens the write
            # transaction, so the claim and the increment are one step under
            # the lock.
            session.refresh(recording)
            _accepting(recording)
            # Claim the sequence BEFORE publishing the file: a replacement
            # phone finalizing the same chunk concurrently used to pass the
            # duplicate check above during the winner's unlocked copy, then
            # hit the unique constraint at commit — a 500 in place of an
            # idempotent ACK, and the loser's bytes won the race to disk while
            # the winner's row won the database. The claim's INSERT begins the
            # write transaction, so the uniqueness check is atomic with the
            # insert; rowcount 0 means we lost to a concurrent claim whose row
            # this transaction's snapshot can already see.
            claim = session.execute(
                sqlite_insert(AudioChunk)
                .values(recording_id=recording.id, sequence_number=sequence,
                        sha256=digest.hexdigest(), size_bytes=size,
                        path=str(target.relative_to(root)))
                .on_conflict_do_nothing(
                    index_elements=["recording_id", "sequence_number"]
                )
            )
            if claim.rowcount == 0:
                existing = session.scalar(select(AudioChunk).where(
                    AudioChunk.recording_id == recording.id,
                    AudioChunk.sequence_number == sequence,
                ))
                winner_sha256 = existing.sha256 if existing is not None else None
                session.rollback()
                if winner_sha256 is None:
                    # The claim lost, yet nothing holds the sequence. Under
                    # SQLite's snapshot that cannot happen; if it ever does,
                    # an ACK here would tell the phone its chunk is stored when
                    # no row says so — and the phone deletes its copy on that
                    # word. A 5xx is transient to the phone: it keeps the chunk
                    # and retries the finalize.
                    log.error("chunk_claim_lost_without_row",
                              recording_id=recording_id_for_log, sequence=sequence)
                    raise HTTPException(500, "Chunk claim conflict; retry the finalize")
                if winner_sha256 != digest.hexdigest():
                    raise HTTPException(409, "Chunk already stored with different content")
                # identical bytes: leave the winner's file in place — it is
                # the same content by definition of the checksum
                return {"acknowledged": True, "duplicate": True,
                        "sha256": digest.hexdigest(), "size_bytes": size}
            os.replace(temporary, target)
            sync_directory(target.parent)
            recording.received_chunks += 1
            recording.updated_at = utcnow()
            session.commit()
        finally:
            temporary.unlink(missing_ok=True)
    return {"acknowledged": True, "duplicate": False,
            "sha256": digest.hexdigest(), "size_bytes": size}
