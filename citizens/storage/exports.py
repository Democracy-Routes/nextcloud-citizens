# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Temporary archive ownership for the single-process app.

Builds run in request threads and streaming finishes on the event loop. Keep
ownership across that handoff so the expiry sweep cannot remove an active file.
After a process restart, abandoned files have no owner and expire normally.
"""

import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from citizens.logging_setup import get_logger
from citizens.storage.paths import exports_dir

log = get_logger(__name__)
_lock = threading.Lock()
_active: set[Path] = set()


def cleanup(path: Path) -> None:
    path = Path(path)
    with _lock:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Release ownership even on failure so the expiry sweep can retry.
            log.warning("export_cleanup_failed", path=path.name, exc_info=True)
        finally:
            _active.discard(path)


@contextmanager
def build_target(root: Path, assembly_id: str, kind: str, retain: bool = False) -> Iterator[Path]:
    directory = exports_dir(root, assembly_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{kind}-{uuid.uuid4()}.zip"
    with _lock:
        _active.add(path)
    try:
        yield path
    except BaseException:
        cleanup(path)
        raise
    else:
        if not retain:
            with _lock:
                _active.discard(path)


def remove_expired(path: Path, cutoff: float) -> int | None:
    """Delete only inactive expired archives; return bytes freed or None."""
    with _lock:
        if path in _active:
            return None
        stat = path.stat()
        if stat.st_mtime >= cutoff:
            return None
        path.unlink(missing_ok=True)
        return stat.st_size
