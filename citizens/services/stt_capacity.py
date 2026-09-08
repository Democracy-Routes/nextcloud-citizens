# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A server-wide ledger of concurrent transcription work, per provider.

Every recording phone opens its own live-caption session — its own ffmpeg and
its own connection to the transcription provider — and batch (final)
transcription adds one more. Nothing bounded that: a plenary room of phones
could saturate a self-hosted Vosk server (or a hosted provider's rate limit),
at which point EVERY session dropped and cycled through failure cooldown,
flashing "captions unavailable" at the whole room.

This ledger is the bound. Live sessions acquire a lease before connecting and
release it when disposed; batch transcription leases around the provider call.
Live and batch are independent pools: keys are "{provider}:live" and
"{provider}:batch". The counter is guarded by a threading.Lock because the two
callers live on different threads: live on the caption event loop, batch on
the job runner's worker thread.

Capacity, not correctness: a denied lease means "not now", never an error —
recording is unaffected and the caller retries on its own clock.
"""

from __future__ import annotations

import threading

from citizens.logging_setup import get_logger

log = get_logger(__name__)

_lock = threading.Lock()
_in_use: dict[str, int] = {}


def try_acquire(key: str, limit: int) -> bool:
    """Take one lease for `key` ("{provider}:{kind}") if fewer than `limit`
    are out."""
    if limit <= 0:
        return False
    with _lock:
        used = _in_use.get(key, 0)
        if used >= limit:
            log.info("stt_capacity_denied", pool=key, in_use=used, limit=limit)
            return False
        _in_use[key] = used + 1
        return True


def release(key: str) -> None:
    """Return one lease. Never goes below zero — a double release is a bug
    upstream, but it must not poison the ledger into refusing work forever."""
    with _lock:
        used = _in_use.get(key, 0)
        if used <= 0:
            log.warning("stt_capacity_double_release", pool=key)
            return
        _in_use[key] = used - 1


def in_use(key: str) -> int:
    with _lock:
        return _in_use.get(key, 0)


def reset_for_tests() -> None:
    with _lock:
        _in_use.clear()
