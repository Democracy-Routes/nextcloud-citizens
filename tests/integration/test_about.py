# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Settings About tab: version, schema, engine, storage, jobs."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from citizens.api.admin import get_config_store, require_admin
from citizens.config import get_settings
from citizens.db.models import AppJob
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.jobs import sweep
from tests.integration.test_admin_providers import MemoryStore


@pytest.fixture
def admin_client(client):
    client.app.dependency_overrides[get_config_store] = lambda: MemoryStore()
    client.app.dependency_overrides[require_admin] = lambda: "tester"
    return client


def _migrations_head() -> str:
    versions = Path(__file__).resolve().parents[2] / "citizens" / "db" / "migrations" / "versions"
    newest = sorted(p.name for p in versions.glob("[0-9]*.py"))[-1]
    for line in (versions / newest).read_text().splitlines():
        if line.startswith("revision"):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise AssertionError("no revision line in " + newest)


def test_about_is_behind_the_admin_guard():
    """Same guard as every other admin route (require_admin is the
    dependency); the negative cases live in test_admin_providers."""
    from citizens.api import admin as admin_module

    route = next(r for r in admin_module.router.routes if r.path == "/admin/about")
    assert any(d.call is admin_module.require_admin for d in route.dependant.dependencies)


def test_about_reports_version_schema_engine_storage_and_jobs(admin_client):
    client = admin_client
    # scheduled in the future so the client's live job runner leaves them be
    later = utcnow() + timedelta(days=1)
    with session_scope() as session:
        session.add(AppJob(type="ANALYZE_TABLE", state="FAILED", last_error="boom"))
        session.add(AppJob(type="TRANSCRIBE", state="QUEUED", next_attempt_at=later))
        session.add(AppJob(type="TRANSCRIBE", state="QUEUED", next_attempt_at=later))
    sweep.LAST_SWEEP_AT = None

    body = client.get("/api/v1/admin/about").json()

    assert body["version"] == get_settings().app_version
    assert body["schema_revision"] == _migrations_head()
    assert body["vosk_mode"] in ("builtin", "server")
    assert body["engine"]["running"] is False
    assert body["storage_ok"] is True
    assert body["disk_free_gb"] is None or body["disk_free_gb"] >= 0
    assert body["jobs"]["queued"] == 2
    assert body["jobs"]["failed"] == 1
    assert body["jobs"]["newest_failure"]["last_error"] == "boom"
    # the client's own runner may already have swept; after an explicit
    # pass the timestamp is a parseable instant either way
    sweep.run_sweeps()
    body = client.get("/api/v1/admin/about").json()
    assert datetime.fromisoformat(body["last_sweep_at"]) <= utcnow()
