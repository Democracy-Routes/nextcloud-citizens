# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The connection pool is sized for the threads that can want a connection,
and a wait for one is measured and reported.

SQLAlchemy's defaults for a file database — 5 + 10, 30 s — were a ceiling
nothing else knew about. Under five phones the request threadpool (40) and
the job workers queued for connections that were parked in OCS calls, and
`QueuePool limit of size 5 overflow 10 reached` was the first visible error.
"""

import threading
import time

from sqlalchemy import create_engine, text

from citizens.db import session as db_session


def test_the_engine_uses_the_measured_pool_at_the_documented_size(settings_env, tmp_path):
    engine = db_session.configure_database(db_session.sqlite_url(tmp_path / "pool.db"))

    assert isinstance(engine.pool, db_session.MeasuredQueuePool)
    assert engine.pool.size() == db_session.POOL_SIZE
    assert engine.pool._max_overflow == db_session.POOL_MAX_OVERFLOW
    status = db_session.pool_status()
    assert status["capacity"] == db_session.POOL_SIZE + db_session.POOL_MAX_OVERFLOW
    assert status["in_use"] == 0


def test_a_long_wait_for_a_connection_is_counted(tmp_path):
    engine = create_engine(
        db_session.sqlite_url(tmp_path / "tiny.db"),
        connect_args={"check_same_thread": False},
        poolclass=db_session.MeasuredQueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=5,
    )
    stats = db_session._pool_stats
    before = stats.slow_waits
    held = engine.connect()
    held.execute(text("SELECT 1"))

    def release_later():
        time.sleep(1.3)
        held.close()

    threading.Thread(target=release_later).start()
    started = time.monotonic()
    with engine.connect() as second:
        second.execute(text("SELECT 1"))
    waited = time.monotonic() - started

    assert waited >= 1.0
    assert stats.slow_waits == before + 1
    assert stats.max_wait_ms >= 1000


def test_health_reports_the_pool(client):
    body = client.get("/api/v1/health").json()

    assert body["pool"]["capacity"] == db_session.POOL_SIZE + db_session.POOL_MAX_OVERFLOW
    assert "max_wait_ms" in body["pool"]
