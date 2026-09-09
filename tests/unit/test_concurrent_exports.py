# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each export owns its archive until its own response ends."""

import asyncio
import os
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from citizens.api import files as files_api
from citizens.db.models import Assembly
from citizens.db.session import read_only_scope, session_scope
from citizens.jobs.sweep import sweep_stale_exports
from citizens.services import files
from citizens.storage import exports


@pytest.fixture
def assembly_id(database, monkeypatch):
    monkeypatch.setattr(files, "build_report", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(files, "render_markdown", lambda _: "report")
    monkeypatch.setattr("citizens.services.branding.logo_path", lambda: None)
    monkeypatch.setattr("citizens.services.branding.organization_name", lambda: "")
    monkeypatch.setattr("citizens.services.report_pdf.render_pdf", lambda *_: b"pdf")
    with session_scope() as session:
        assembly = Assembly(name="Concurrent", created_by="tester")
        session.add(assembly)
        session.flush()
        return assembly.id


def _age(path):
    old = time.time() - 7200
    os.utime(path, (old, old))


@pytest.mark.parametrize("builder", ["build_audio_zip", "build_session_export"])
def test_simultaneous_builds_keep_separate_valid_archives(assembly_id, monkeypatch, builder):
    barrier = threading.Barrier(2)
    real_build = getattr(files, "_" + builder)

    def overlap(session, assembly, target):
        barrier.wait(timeout=10)
        return real_build(session, assembly, target)

    monkeypatch.setattr(files, "_" + builder, overlap)

    def build():
        with read_only_scope() as session:
            return getattr(files, builder)(session, session.get(Assembly, assembly_id), retain=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = [f.result(timeout=20) for f in [pool.submit(build), pool.submit(build)]]
    try:
        assert first != second
        for path in (first, second):
            with zipfile.ZipFile(path) as archive:
                assert archive.testzip() is None
        exports.cleanup(first)
        assert second.exists()
        with zipfile.ZipFile(second) as archive:
            assert archive.testzip() is None
    finally:
        exports.cleanup(first)
        exports.cleanup(second)


def test_sweep_skips_active_build_and_stream(assembly_id, monkeypatch):
    real_build = files._build_audio_zip

    def slow_build(session, assembly, target):
        target.touch()
        _age(target)
        assert sweep_stale_exports() == 0
        assert target.exists()
        return real_build(session, assembly, target)

    monkeypatch.setattr(files, "_build_audio_zip", slow_build)
    with read_only_scope() as session:
        path = files.build_audio_zip(session, session.get(Assembly, assembly_id), retain=True)
    try:
        _age(path)
        assert sweep_stale_exports() == 0
        assert path.exists()
    finally:
        exports.cleanup(path)


@pytest.mark.parametrize("builder", ["build_audio_zip", "build_session_export"])
def test_build_failure_removes_partial_and_releases_ownership(assembly_id, monkeypatch, builder):
    paths = []

    def fail(_session, _assembly, target):
        paths.append(target)
        target.write_bytes(b"partial archive")
        raise OSError("disk full")

    monkeypatch.setattr(files, "_" + builder, fail)
    with read_only_scope() as session, pytest.raises(OSError, match="disk full"):
        getattr(files, builder)(session, session.get(Assembly, assembly_id), retain=True)
    path = paths[0]
    assert not path.exists()
    # Recreating an abandoned artifact at the old path must not inherit a lease.
    path.write_bytes(b"abandoned")
    _age(path)
    assert sweep_stale_exports() == 1


@pytest.mark.parametrize("failure", [None, OSError, asyncio.CancelledError])
def test_response_always_cleans_up(assembly_id, failure):
    with read_only_scope() as session:
        path = files.build_audio_zip(session, session.get(Assembly, assembly_id), retain=True)
    response = files_api._zip_response(path, "audio.zip")
    messages = []

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body" and failure:
            raise failure()

    async def receive():
        return {"type": "http.disconnect"}

    async def run():
        await response({
            "type": "http", "method": "GET", "headers": [],
            "extensions": {"http.response.pathsend": {}},
        }, receive, send)

    if failure:
        with pytest.raises(failure):
            asyncio.run(run())
    else:
        asyncio.run(run())
        assert any(m["type"] == "http.response.body" and m.get("body") for m in messages)
    assert not path.exists()
    assert not any(m["type"] == "http.response.pathsend" for m in messages)
    path.write_bytes(b"abandoned")
    _age(path)
    assert sweep_stale_exports() == 1


@pytest.mark.parametrize("endpoint", [files_api.download_all_audio, files_api.download_session_export])
def test_audit_failure_cleans_up_before_response(assembly_id, database, monkeypatch, endpoint):
    def fail(*_):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(files_api, "_audit_after_build", fail)
    with read_only_scope() as session, pytest.raises(RuntimeError, match="audit unavailable"):
        endpoint(assembly_id, "tester", session)
    assert list((database.app_persistent_storage / "exports").glob("*/*.zip")) == []


def test_completed_direct_build_expires(assembly_id):
    with read_only_scope() as session:
        path = files.build_audio_zip(session, session.get(Assembly, assembly_id))
    _age(path)
    assert sweep_stale_exports() == 1
    assert not path.exists()
