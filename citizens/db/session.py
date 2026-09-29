# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Database engine/session management.

SQLite in APP_PERSISTENT_STORAGE with WAL mode and enforced foreign keys.
Kept behind small functions so PostgreSQL could be supported later without
touching callers.
"""

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from citizens.logging_setup import get_logger

log = get_logger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker | None = None
_read_session_factory: sessionmaker | None = None

# Connection budget. SQLAlchemy's defaults for a file database are 5 + 10
# with a 30 s wait — a ceiling nothing else in the app knew about: the
# request threadpool alone can hold 40 and the job workers ten more, so
# under load requests queued for a connection long before the database
# itself was busy. SQLite connections are file handles; readers in WAL mode
# run side by side; the single writer slot is the real limit and busy_timeout
# already queues on it. Enough slots for every thread that can want one.
POOL_SIZE = 16
POOL_MAX_OVERFLOW = 40
POOL_TIMEOUT_SECONDS = 15
# a wait this long for a connection means the app is in trouble: say so
POOL_WAIT_WARN_SECONDS = 1.0
_POOL_WARN_EVERY_SECONDS = 10.0


class _PoolStats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.max_wait_ms = 0.0
        self.slow_waits = 0
        self.last_warned = 0.0

    def note(self, waited: float) -> None:
        with self.lock:
            self.max_wait_ms = max(self.max_wait_ms, waited * 1000)
            if waited < POOL_WAIT_WARN_SECONDS:
                return
            self.slow_waits += 1
            now = time.monotonic()
            warn = now - self.last_warned >= _POOL_WARN_EVERY_SECONDS
            if warn:
                self.last_warned = now
        if warn:
            log.warning("db_pool_wait", waited_ms=round(waited * 1000), slow_waits=self.slow_waits)


_pool_stats = _PoolStats()


class MeasuredQueuePool(QueuePool):
    """QueuePool that measures how long a checkout waited for a connection.

    The pool has no event for "waited": checkout fires once a connection is
    in hand. Timing the get itself is the only honest measurement, and it is
    what the health endpoint and the status screen report.
    """

    def _do_get(self):
        started = time.monotonic()
        try:
            return super()._do_get()
        finally:
            _pool_stats.note(time.monotonic() - started)


def pool_status() -> dict:
    """Connections in use and the worst wait seen — for /health and the
    operator's status screen."""
    status = {
        "in_use": None,
        "capacity": POOL_SIZE + POOL_MAX_OVERFLOW,
        "max_wait_ms": round(_pool_stats.max_wait_ms),
        "slow_waits": _pool_stats.slow_waits,
    }
    if _engine is not None and isinstance(_engine.pool, QueuePool):
        status["in_use"] = _engine.pool.checkedout()
    return status


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def configure_database(db_url: str) -> Engine:
    global _engine, _session_factory, _read_session_factory
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    pool_kwargs: dict = {}
    if db_url.startswith("sqlite") and ":memory:" not in db_url:
        pool_kwargs = {
            "poolclass": MeasuredQueuePool,
            "pool_size": POOL_SIZE,
            "max_overflow": POOL_MAX_OVERFLOW,
            "pool_timeout": POOL_TIMEOUT_SECONDS,
        }
    _engine = create_engine(db_url, connect_args=connect_args, **pool_kwargs)
    if db_url.startswith("sqlite"):
        event.listen(_engine, "connect", _set_sqlite_pragmas)
        # BEGIN IMMEDIATE: take the write lock at transaction start so
        # concurrent writers queue on busy_timeout instead of failing with
        # "database is locked" on a read→write lock upgrade.
        event.listen(_engine, "begin", _begin_immediate)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    _read_session_factory = sessionmaker(
        bind=_engine.execution_options(citizens_read_only=True), expire_on_commit=False
    )
    return _engine


def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    # let SQLAlchemy control transactions entirely (no driver-level auto-BEGIN)
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=10000")
    cursor.execute("PRAGMA synchronous=FULL")
    cursor.close()


def _begin_immediate(conn) -> None:
    # Read-only sessions opt out: taking the single writer slot for a query
    # that cannot write throws away WAL's whole point, and polling endpoints
    # (captions, status, monitor) are most of the traffic at twenty tables.
    if conn.get_execution_options().get("citizens_read_only"):
        return
    conn.exec_driver_sql("BEGIN IMMEDIATE")


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database is not configured; call configure_database() first")
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    if _session_factory is None:
        raise RuntimeError("Database is not configured; call configure_database() first")
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session


@contextmanager
def read_only_scope() -> Iterator[Session]:
    """A session that does NOT take SQLite's write lock.

    Bound to an engine carrying the `citizens_read_only` execution option,
    which `_begin_immediate` checks. Always rolled back: nothing reached
    through here is allowed to have changed anything.
    """
    if _read_session_factory is None:
        raise RuntimeError("Database is not configured; call configure_database() first")
    session = _read_session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def get_read_db() -> Iterator[Session]:
    """FastAPI dependency for endpoints that only read."""
    with read_only_scope() as session:
        yield session
