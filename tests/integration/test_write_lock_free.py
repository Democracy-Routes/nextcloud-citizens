# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Slow endpoints must not hold SQLite's single writer slot.

SQLite has one writer, and `_begin_immediate` claims it at transaction start.
An endpoint that keeps a write session open while it copies a gigabyte of audio
into a zip, renders a PDF, or waits on an HTTPS round-trip to Nextcloud makes
every phone uploading a chunk queue on `busy_timeout` (10 s) and then fail with
"database is locked" — a 500 to a table mid-recording.

Each test below monkeypatches the slow work so it probes the writer slot at the
moment it runs. Before the read-session conversion every one of these fails.
"""

import re

import pytest

from citizens.services import files as files_svc
from citizens.services import invites as invite_svc
from citizens.services import provider_config


def _assembly(client, name="TEST Write Lock"):
    return client.post(
        "/api/v1/assemblies",
        json={
            "name": name,
            "default_table_count": 2,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()


def _probing(probe, real):
    """Wrap the slow work so it asserts the writer slot is free first."""

    def wrapper(*args, **kwargs):
        probe()
        return real(*args, **kwargs)

    return wrapper


def test_the_audio_bundle_is_built_without_the_write_lock(
    client, monkeypatch, writer_slot_probe
):
    assembly = _assembly(client)
    monkeypatch.setattr(
        files_svc, "build_audio_zip", _probing(writer_slot_probe, files_svc.build_audio_zip)
    )
    response = client.get(f"/api/v1/assemblies/{assembly['id']}/audio.zip")
    assert response.status_code == 200


def test_the_session_export_is_built_without_the_write_lock(
    client, monkeypatch, writer_slot_probe
):
    assembly = _assembly(client)
    monkeypatch.setattr(
        files_svc,
        "build_session_export",
        _probing(writer_slot_probe, files_svc.build_session_export),
    )
    response = client.get(f"/api/v1/assemblies/{assembly['id']}/export.zip")
    assert response.status_code == 200


def test_the_file_listing_does_not_take_the_write_lock(client, writer_slot_probe):
    assembly = _assembly(client)
    with client.stream("GET", f"/api/v1/assemblies/{assembly['id']}/files") as response:
        assert response.status_code == 200
        writer_slot_probe()


def test_the_qr_sheet_is_rendered_without_the_write_lock(
    client, monkeypatch, writer_slot_probe
):
    """The sheet is printed at the door while tables are already joining."""
    assembly = _assembly(client)
    client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate")
    monkeypatch.setattr(
        invite_svc, "invite_links", _probing(writer_slot_probe, invite_svc.invite_links)
    )
    response = client.get(f"/api/v1/assemblies/{assembly['id']}/invites/sheet.pdf")
    assert response.status_code == 200


def test_the_report_is_built_without_the_write_lock(client, monkeypatch, writer_slot_probe):
    # patched on the api module, not the service: reports.py imports
    # build_report by name, so the service attribute is not what it calls
    import citizens.api.reports as reports_api

    assembly = _assembly(client)
    monkeypatch.setattr(
        reports_api, "build_report", _probing(writer_slot_probe, reports_api.build_report)
    )
    response = client.get(f"/api/v1/assemblies/{assembly['id']}/report")
    assert response.status_code == 200


def test_joining_never_holds_the_write_lock_across_a_config_read(
    client, monkeypatch, writer_slot_probe
):
    """Twenty tables scan their QR codes inside the same minute. If join holds
    the writer slot while asking Nextcloud for the data-handling summary, the
    chunk uploads already in flight queue behind an HTTPS round-trip."""
    assembly = _assembly(client)
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)

    import citizens.api.public_recorder as pr

    real = pr.data_handling_summary
    monkeypatch.setattr(pr, "data_handling_summary", _probing(writer_slot_probe, real))
    monkeypatch.setattr(
        provider_config,
        "analysis_enabled_cached",
        _probing(writer_slot_probe, provider_config.analysis_enabled_cached),
    )

    response = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Origin-IP": "203.0.113.7"}
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "suffix", ["report", "progress", "files"]
)
def test_read_endpoints_leave_the_writer_slot_free(client, writer_slot_probe, suffix):
    assembly = _assembly(client)
    with client.stream("GET", f"/api/v1/assemblies/{assembly['id']}/{suffix}") as response:
        assert response.status_code == 200
        writer_slot_probe()
