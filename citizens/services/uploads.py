# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whole files from the organizer page, received in parts.

A request body through the AppAPI proxy is capped at a few megabytes
(api/limits.py), and a session export or a table's audio is far bigger. So
the page opens an upload, posts 5 MB parts, and closes it with the SHA-256
of the whole file. Only a closed upload whose hash matched can be consumed
(a session import, an attached transcript or audio), and consuming it
deletes it.

Nothing here touches the database: an upload is a directory under the
storage root's temp area holding a small `meta.json` and one file per part.
A process restart loses nothing, the sweep removes what nobody finished
within a day, and the organizer who opened an upload is the only one who
can add to it or use it.
"""

import hashlib
import json
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from citizens.config import get_settings
from citizens.logging_setup import get_logger
from citizens.storage.paths import temp_dir
from citizens.storage.space import has_room_for, require_room

log = get_logger(__name__)

PART_BYTES = 5 * 1024 * 1024
KINDS = ("session_export", "transcript", "audio")
#: a transcript is text; an export carries every table's audio
MAX_BYTES = {"session_export": 4 * 1024**3, "transcript": 64 * 1024**2, "audio": 2 * 1024**3}
UPLOAD_TTL_SECONDS = 24 * 3600
MAX_OPEN_UPLOADS_PER_OWNER = 3


class UploadError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass
class UploadMeta:
    upload_id: str
    owner: str
    kind: str
    filename: str
    size_bytes: int
    parts: int
    created_at: float
    complete: bool = False
    sha256: str = ""


def _root() -> Path:
    return temp_dir(get_settings().app_persistent_storage) / "uploads"


def _dir(upload_id: str) -> Path:
    # ids are ours (uuid4), so this never leaves the uploads directory
    if not uuid_like(upload_id):
        raise UploadError(404, "Upload not found")
    return _root() / upload_id


def uuid_like(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        return False


def _part_path(directory: Path, index: int) -> Path:
    return directory / f"{index:06d}.part"


def _read_meta(directory: Path) -> UploadMeta:
    try:
        return UploadMeta(**json.loads((directory / "meta.json").read_text()))
    except (OSError, ValueError, TypeError) as exc:
        raise UploadError(404, "Upload not found") from exc


def _write_meta(directory: Path, meta: UploadMeta) -> None:
    (directory / "meta.json").write_text(json.dumps(asdict(meta)))


def begin(owner: str, kind: str, filename: str, size_bytes: int) -> UploadMeta:
    if kind not in KINDS:
        raise UploadError(422, "Unknown upload kind")
    if size_bytes <= 0:
        raise UploadError(422, "An empty file cannot be uploaded")
    if size_bytes > MAX_BYTES[kind]:
        raise UploadError(413, f"A {kind.replace('_', ' ')} may be at most {MAX_BYTES[kind] >> 20} MB")
    root = get_settings().app_persistent_storage
    _root().mkdir(parents=True, exist_ok=True)
    open_mine = 0
    reserved = 0
    for directory in _root().iterdir():
        if not directory.is_dir():
            continue
        try:
            other = _read_meta(directory)
        except UploadError:
            continue
        if other.complete:
            continue
        reserved += other.size_bytes
        if other.owner == owner:
            open_mine += 1
    if open_mine >= MAX_OPEN_UPLOADS_PER_OWNER:
        raise UploadError(409, "Finish or discard an open upload first")
    # the parts plus the file they become, both on this disk for a while,
    # and what every other open upload has still to take
    if not has_room_for(root, size_bytes * 2 + reserved):
        raise UploadError(507, "Not enough free storage for this file")
    meta = UploadMeta(
        upload_id=str(uuid.uuid4()),
        owner=owner,
        kind=kind,
        filename=Path(filename or "upload").name[:200],
        size_bytes=size_bytes,
        parts=(size_bytes + PART_BYTES - 1) // PART_BYTES,
        created_at=time.time(),
    )
    directory = _root() / meta.upload_id
    directory.mkdir(parents=True, exist_ok=False)
    _write_meta(directory, meta)
    log.info("upload_opened", upload_id=meta.upload_id, kind=kind, size_bytes=size_bytes)
    return meta


def owned(upload_id: str, owner: str) -> tuple[Path, UploadMeta]:
    """404 for missing and for somebody else's alike."""
    directory = _dir(upload_id)
    if not directory.is_dir():
        raise UploadError(404, "Upload not found")
    meta = _read_meta(directory)
    if meta.owner != owner:
        raise UploadError(404, "Upload not found")
    return directory, meta


def store_part(upload_id: str, owner: str, index: int, body: bytes) -> dict:
    directory, meta = owned(upload_id, owner)
    if meta.complete:
        raise UploadError(409, "This upload is already complete")
    if not 0 <= index < meta.parts:
        raise UploadError(422, f"Part {index} is outside this upload's {meta.parts} parts")
    expected = PART_BYTES if index < meta.parts - 1 else meta.size_bytes - PART_BYTES * (meta.parts - 1)
    if len(body) != expected:
        raise UploadError(422, f"Part {index} should be {expected} bytes, got {len(body)}")
    require_room(get_settings().app_persistent_storage, len(body), context="upload_part")
    _part_path(directory, index).write_bytes(body)
    received = [p for p in range(meta.parts) if _part_path(directory, p).is_file()]
    return {
        "upload_id": upload_id,
        "parts_received": len(received),
        "bytes_received": sum(_part_path(directory, p).stat().st_size for p in received),
    }


def complete(upload_id: str, owner: str, sha256: str) -> UploadMeta:
    """Join the parts into one file and check the hash of the whole."""
    directory, meta = owned(upload_id, owner)
    if meta.complete:
        return meta
    missing = [p for p in range(meta.parts) if not _part_path(directory, p).is_file()]
    if missing:
        raise UploadError(422, f"{len(missing)} of {meta.parts} parts never arrived")
    require_room(get_settings().app_persistent_storage, meta.size_bytes, context="upload_join")
    target = directory / "file"
    digest = hashlib.sha256()
    with target.open("wb") as whole:
        for index in range(meta.parts):
            part = _part_path(directory, index)
            data = part.read_bytes()
            digest.update(data)
            whole.write(data)
    if digest.hexdigest() != sha256.lower():
        target.unlink(missing_ok=True)
        raise UploadError(422, "The file arrived damaged: its checksum does not match")
    for index in range(meta.parts):
        _part_path(directory, index).unlink(missing_ok=True)
    meta.complete = True
    meta.sha256 = sha256.lower()
    _write_meta(directory, meta)
    log.info("upload_completed", upload_id=upload_id, kind=meta.kind, size_bytes=meta.size_bytes)
    return meta


def take(upload_id: str, owner: str, kind: str) -> tuple[Path, UploadMeta]:
    """The finished file of a completed upload of this kind, for a consumer.
    The consumer calls discard() when done, whatever happened."""
    directory, meta = owned(upload_id, owner)
    if not meta.complete:
        raise UploadError(409, "The upload is not complete")
    if meta.kind != kind:
        raise UploadError(
            422, f"This upload is a {meta.kind.replace('_', ' ')}, not a {kind.replace('_', ' ')}"
        )
    path = directory / "file"
    if not path.is_file():
        raise UploadError(404, "Upload not found")
    return path, meta


def discard(upload_id: str, owner: str | None = None) -> bool:
    try:
        directory = _dir(upload_id)
    except UploadError:
        return False
    if not directory.is_dir():
        return False
    if owner is not None:
        meta = _read_meta(directory)
        if meta.owner != owner:
            raise UploadError(404, "Upload not found")
    shutil.rmtree(directory, ignore_errors=True)
    return True


def sweep_stale(now: float | None = None) -> int:
    """Remove uploads nobody finished or consumed within the TTL. No database."""
    root = _root()
    if not root.is_dir():
        return 0
    cutoff = (now or time.time()) - UPLOAD_TTL_SECONDS
    removed = 0
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        try:
            created = _read_meta(directory).created_at
        except UploadError:
            created = directory.stat().st_mtime
        if created < cutoff:
            shutil.rmtree(directory, ignore_errors=True)
            removed += 1
            log.info("stale_upload_removed", upload_id=directory.name)
    return removed
