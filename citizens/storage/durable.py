# SPDX-License-Identifier: AGPL-3.0-or-later
"""Publish audio bytes only after their file and directory entries are durable."""
import os
import tempfile
from pathlib import Path


def sync_directory(path: Path):
    path = path.resolve()
    root = path.anchor
    # Newly created ancestors must survive a power loss too, not just the file.
    while str(path) != root:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        path = path.parent


def write_audio(target: Path, data: bytes):
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as out:
        temporary = Path(out.name)
        try:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
            os.replace(temporary, target)
            sync_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)
