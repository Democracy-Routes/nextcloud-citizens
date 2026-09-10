# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Database engine/session management.

SQLite in APP_PERSISTENT_STORAGE with WAL mode and enforced foreign keys.
Kept behind small functions so PostgreSQL could be supported later without
touching callers.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_session_factory: sessionmaker | None = None
_read_session_factory: sessionmaker | None = None


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def configure_database(db_url: str) -> Engine:
    global _engine, _session_factory, _read_session_factory
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    _engine = create_engine(db_url, connect_args=connect_args)
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
