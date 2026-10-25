# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Speech models for the built-in Vosk engine (0.8): a catalogue of the
public alphacephei models per language, one-click installs as background
jobs with progress, and removal — so an admin never touches a shell.

Installs are atomic: the zip streams into temp/, unpacks beside it, and the
finished directory is moved into models/<name> in one rename; a crash or a
cancel leaves nothing half-installed."""

from __future__ import annotations

import re
import shutil
import threading
import time
import zipfile
from pathlib import Path

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.logging_setup import get_logger
from citizens.services.audit import record_audit_event
from citizens.services.jobs import enqueue_job, has_live_job
from citizens.storage.paths import models_dir, temp_dir
from citizens.storage.space import has_room_for

log = get_logger(__name__)

JOB_TYPE = "INSTALL_VOSK_MODEL"
NAME_RE = re.compile(r"^vosk-model-[a-z0-9.-]+$")
BASE_URL = "https://alphacephei.com/vosk/models/"
#: sizes as published on alphacephei.com/vosk/models (zip, rounded up)
CATALOGUE: list[dict] = [
    {"name": "vosk-model-small-it-0.22", "language": "it", "kind": "small", "size_mb": 48},
    {"name": "vosk-model-it-0.22", "language": "it", "kind": "large", "size_mb": 1200},
    {"name": "vosk-model-small-en-us-0.15", "language": "en", "kind": "small", "size_mb": 40},
    {"name": "vosk-model-en-us-0.22", "language": "en", "kind": "large", "size_mb": 1800},
    {"name": "vosk-model-small-de-0.15", "language": "de", "kind": "small", "size_mb": 45},
    {"name": "vosk-model-de-0.21", "language": "de", "kind": "large", "size_mb": 1900},
    {"name": "vosk-model-small-fr-0.22", "language": "fr", "kind": "small", "size_mb": 41},
    {"name": "vosk-model-fr-0.22", "language": "fr", "kind": "large", "size_mb": 1400},
    {"name": "vosk-model-small-es-0.42", "language": "es", "kind": "small", "size_mb": 39},
    {"name": "vosk-model-es-0.42", "language": "es", "kind": "large", "size_mb": 1400},
]
#: what the directory of a usable model always contains
MODEL_MARKERS = ("am", "conf")

#: name -> {phase, received, total, error, started_at}; the Settings page polls
#: it. In memory on purpose: a restart cancels the download and the next
#: GET says so (the job row is what survives).
PROGRESS: dict[str, dict] = {}
_CANCEL: set[str] = set()
_lock = threading.Lock()


def _root() -> Path:
    return get_settings().app_persistent_storage


def catalogue_entry(name: str) -> dict | None:
    return next((entry for entry in CATALOGUE if entry["name"] == name), None)


def language_of(name: str) -> str:
    entry = catalogue_entry(name)
    if entry:
        return entry["language"]
    match = re.match(r"^vosk-model-(?:small-)?([a-z]{2})", name)
    return match.group(1) if match else ""


def installed(root: Path | None = None) -> list[dict]:
    """Every usable model directory under models/, with its size."""
    directory = models_dir(root or _root())
    found = []
    if not directory.is_dir():
        return found
    for child in sorted(directory.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        usable = all((child / marker).exists() for marker in MODEL_MARKERS)
        size = sum(f.stat().st_size for f in child.rglob("*") if f.is_file())
        entry = catalogue_entry(child.name) or {}
        found.append({
            "name": child.name,
            "language": language_of(child.name),
            "kind": entry.get("kind", "custom"),
            "size_bytes": size,
            "usable": usable,
        })
    return found


def overview(root: Path | None = None) -> dict:
    from citizens.services.vosk_builtin import BUILTIN, memory_available

    have = installed(root)
    names = {m["name"] for m in have}
    with _lock:
        progress = {name: dict(state) for name, state in PROGRESS.items()}
    available = [
        {**entry, "progress": progress.get(entry["name"])}
        for entry in CATALOGUE
        if entry["name"] not in names
    ]
    return {
        "installed": have,
        "available": available,
        "engine": BUILTIN.status(),
        "memory_available_bytes": memory_available(),
    }


def _set_progress(name: str, **fields) -> None:
    with _lock:
        state = PROGRESS.setdefault(name, {"phase": "queued", "received": 0, "total": None,
                                           "error": None, "started_at": time.time()})
        state.update(fields)


def request_install(session: Session, name: str, actor: str) -> dict:
    if not NAME_RE.match(name or ""):
        raise HTTPException(status_code=422, detail="Not a model name")
    entry = catalogue_entry(name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown model")
    if name in {m["name"] for m in installed()}:
        raise HTTPException(status_code=409, detail="Already installed")
    if has_live_job(session, JOB_TYPE, "name", name):
        raise HTTPException(status_code=409, detail="Already installing")
    # the zip and the unpacked model both live on the volume for a moment
    if not has_room_for(_root(), entry["size_mb"] * 1024 * 1024 * 2):
        raise HTTPException(status_code=507, detail="Not enough free space for this model")
    _CANCEL.discard(name)
    _set_progress(name, phase="queued", received=0, total=entry["size_mb"] * 1024 * 1024, error=None)
    enqueue_job(session, JOB_TYPE, {"name": name}, max_attempts=2)
    record_audit_event(session, "vosk_model_install_requested", "vosk_model", name, actor=actor)
    return {"queued": True, "name": name}


def cancel_install(name: str) -> dict:
    with _lock:
        state = PROGRESS.get(name)
    if state is None or state["phase"] in ("done", "failed"):
        raise HTTPException(status_code=404, detail="Nothing to cancel")
    _CANCEL.add(name)
    return {"cancelling": True}


def remove(session: Session, name: str, actor: str) -> dict:
    from citizens.services.vosk_builtin import BUILTIN

    if not NAME_RE.match(name or ""):
        raise HTTPException(status_code=422, detail="Not a model name")
    target = models_dir(_root()) / name
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Not installed")
    if BUILTIN.in_use(name):
        raise HTTPException(status_code=409, detail="This model is in use by a live session")
    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    shutil.rmtree(target)
    with _lock:
        PROGRESS.pop(name, None)
    record_audit_event(
        session, "vosk_model_removed", "vosk_model", name, actor=actor, data={"freed_bytes": size}
    )
    log.info("vosk_model_removed", model=name, freed_bytes=size)
    return {"removed": True, "name": name, "freed_bytes": size}


# ---- the job ---------------------------------------------------------------


class InstallCancelled(Exception):
    pass


def _download(url: str, target: Path, name: str) -> None:
    received = 0
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(60, connect=30)) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0) or None
        _set_progress(name, phase="downloading", received=0, total=total)
        with target.open("wb") as out:
            for chunk in r.iter_bytes(1024 * 1024):
                if name in _CANCEL:
                    raise InstallCancelled()
                out.write(chunk)
                received += len(chunk)
                _set_progress(name, received=received)


def _unpack(archive: Path, scratch: Path, name: str) -> Path:
    """The model directory inside the zip (alphacephei zips hold one
    top-level directory named like the model), unpacked under scratch."""
    _set_progress(name, phase="unpacking")
    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            if member.startswith("/") or ".." in Path(member).parts:
                raise ValueError(f"unsafe path in archive: {member}")
        zf.extractall(scratch)
    candidates = [child for child in scratch.iterdir() if child.is_dir()]
    for candidate in candidates:
        if all((candidate / marker).exists() for marker in MODEL_MARKERS):
            return candidate
    if all((scratch / marker).exists() for marker in MODEL_MARKERS):
        return scratch
    raise ValueError("the archive does not contain a Vosk model")


def handle_install_vosk_model(session: Session, payload: dict) -> None:
    from citizens.jobs.handlers import PermanentJobError

    name = payload["name"]
    entry = catalogue_entry(name)
    if entry is None:
        raise PermanentJobError(f"unknown model {name}")
    root = _root()
    final = models_dir(root) / name
    if final.is_dir():
        _set_progress(name, phase="done")
        return
    scratch = temp_dir(root) / f"vosk-{name}"
    archive = temp_dir(root) / f"vosk-{name}.zip"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        _download(BASE_URL + name + ".zip", archive, name)
        model_dir = _unpack(archive, scratch, name)
        final.parent.mkdir(parents=True, exist_ok=True)
        model_dir.replace(final)
        _set_progress(name, phase="done", error=None)
        record_audit_event(
            session, "vosk_model_installed", "vosk_model", name,
            data={"bytes": sum(f.stat().st_size for f in final.rglob("*") if f.is_file())},
        )
        log.info("vosk_model_installed", model=name)
    except InstallCancelled:
        _set_progress(name, phase="failed", error="cancelled")
        log.info("vosk_model_install_cancelled", model=name)
        raise PermanentJobError("cancelled") from None
    except (httpx.HTTPError, OSError, ValueError, zipfile.BadZipFile) as exc:
        _set_progress(name, phase="failed", error=f"{type(exc).__name__}: {exc}"[:200])
        log.warning("vosk_model_install_failed", model=name, error=str(exc)[:200])
        raise PermanentJobError(str(exc)) from exc
    finally:
        archive.unlink(missing_ok=True)
        shutil.rmtree(scratch, ignore_errors=True)
        _CANCEL.discard(name)
