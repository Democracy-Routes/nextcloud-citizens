# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from citizens.config import get_settings
from citizens.db.migrate import run_migrations
from citizens.db.session import configure_database, get_engine, sqlite_url
from citizens.main import create_app
from citizens.security.identity import get_current_user_id


@pytest.fixture
def settings_env(tmp_path, monkeypatch):
    """Point the app at a temporary storage dir and return fresh settings."""
    monkeypatch.setenv("APP_ID", "citizens")
    monkeypatch.setenv("APP_VERSION", "0.0.0-test")
    monkeypatch.setenv("APP_SECRET", "test-secret")
    monkeypatch.setenv("NEXTCLOUD_URL", "http://nextcloud.test")
    monkeypatch.setenv("APP_PERSISTENT_STORAGE", str(tmp_path / "storage"))
    monkeypatch.setenv("CITIZENS_DEV", "0")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def client(settings_env):
    """App without AppAPI signature auth; identity comes from the X-Test-User
    header (default 'tester') so ownership rules can be exercised."""
    app = create_app(with_auth=False)

    def fake_user(request: Request) -> str:
        return request.headers.get("x-test-user", "tester")

    app.dependency_overrides[get_current_user_id] = fake_user
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def writer_slot_probe():
    """Assert SQLite's single writer slot is free RIGHT NOW.

    `_begin_immediate` claims that slot at transaction start, so any endpoint
    that keeps a write session open while it copies a gigabyte of audio, renders
    a PDF or waits on an HTTPS round-trip starves every phone uploading chunks.
    Reproducing that as a timeout takes 10 seconds (`busy_timeout`) and is
    flaky; this makes it an immediate, deterministic assertion instead.

    Use it by monkeypatching the slow work to call the probe first:

        monkeypatch.setattr(files_svc, "build_audio_zip", probing(real))
    """

    def probe() -> None:
        raw = get_engine().raw_connection()
        try:
            cursor = raw.cursor()
            cursor.execute("PRAGMA busy_timeout=200")
            try:
                cursor.execute("BEGIN IMMEDIATE")
            except Exception as exc:  # sqlite3.OperationalError: database is locked
                raise AssertionError(
                    "the write lock is held here — a phone uploading a chunk "
                    "would queue on busy_timeout and fail"
                ) from exc
            cursor.execute("ROLLBACK")
            cursor.close()
        finally:
            raw.close()

    return probe


@pytest.fixture
def database(settings_env):
    """A migrated database with NO application running.

    The `client` fixture starts the real job runner, which competes for queued
    jobs — so a test that asserts something about claiming or scheduling races
    it and fails intermittently. This gives the schema without the worker.
    """
    from citizens.storage.paths import db_path, ensure_storage_layout

    ensure_storage_layout(settings_env.app_persistent_storage)
    url = sqlite_url(db_path(settings_env.app_persistent_storage))
    configure_database(url)
    run_migrations(url)
    return settings_env
