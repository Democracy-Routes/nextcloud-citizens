# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small in-memory rate limiter for public endpoints (single-process app).

Not a substitute for infrastructure-level protection, but keeps token
brute-forcing and accidental client loops in check.
"""

import hashlib
import threading
import time

from fastapi import HTTPException, Request


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            events = [t for t in self._events.get(key, []) if now - t < self.window_seconds]
            if len(events) >= self.max_events:
                self._events[key] = events
                raise HTTPException(status_code=429, detail="Too many requests")
            events.append(now)
            self._events[key] = events
            # opportunistic cleanup so the dict cannot grow unbounded
            if len(self._events) > 10000:
                cutoff = now - self.window_seconds
                self._events = {
                    k: [t for t in v if t > cutoff] for k, v in self._events.items() if v and v[-1] > cutoff
                }


# Per invite token: one table's phone should never need more than a handful of
# attempts, and each table gets its own budget. Keying on the IP instead used to
# reject tables 11+ at a venue, where every phone shares one NAT'd address.
JOIN_TOKEN_LIMITER = SlidingWindowLimiter(max_events=10, window_seconds=60)
# Coarse flood backstop. Deliberately far above any legitimate assembly: with a
# reverse proxy in front, this key can collapse to a single address for every
# phone, so it must never be the thing that stops a room full of tables.
JOIN_IP_LIMITER = SlidingWindowLimiter(max_events=120, window_seconds=60)

# A joined phone making codes for the next phone: a handful a minute is a room
# adding tables and recorders, hundreds is a script. Keyed by recorder session.
CAPABILITY_LIMITER = SlidingWindowLimiter(max_events=20, window_seconds=60)
# Need help from a table: one open request per table anyway, so a handful a
# minute per phone is a nervous tapper, not a use case
HELP_LIMITER = SlidingWindowLimiter(max_events=6, window_seconds=60)


def token_key(token: str) -> str:
    """Bucket key for an invite token — hashed so raw invite secrets are not
    held in process memory or surfaced by a traceback."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def client_ip(request: Request) -> str:
    """AppAPI sets `x-origin-ip` itself, stripping any client-supplied copy, so
    it is the only trustworthy client address behind the proxy. X-Forwarded-For
    is accepted only as a fallback for direct deployments — it is
    client-controlled, and preferring it let anyone reset their own bucket with
    a made-up header.
    """
    origin = request.headers.get("x-origin-ip", "").strip()
    if origin:
        return origin
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
