# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Block 3 housekeeping: the device report through the API (R17), the
7-day cleanup of what expired (R24), failed syntheses on the progress
route (R25)."""

import json
import re
from datetime import timedelta

from sqlalchemy import select

from citizens.db.models import AppJob, RecorderInvite, RecorderSession, Recording
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.jobs import sweep
from citizens.storage.paths import device_log_path


def _assembly(client, name="TEST Housekeeping"):
    return client.post(
        "/api/v1/assemblies",
        json={"name": name, "default_table_count": 2,
              "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}]},
    ).json()


def _join(client, url, ip="10.20.0.1"):
    token = re.search(r"#/join/(.+)$", url).group(1)
    return client.post("/api/v1/public/join", json={"token": token},
                       headers={"X-Forwarded-For": ip}).json()


def test_the_device_report_reads_each_phone_log(client, settings_env):
    assembly = _assembly(client)
    joined = _join(client, assembly["invites"][0]["url"])
    with session_scope() as session:
        session_id = session.execute(
            select(RecorderSession.id).where(RecorderSession.assembly_id == assembly["id"])
        ).scalar_one()
    path = device_log_path(settings_env.app_persistent_storage, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"ts": 1_760_000_000.0, "event": "device_info",
            "data": {"ua": "Mozilla/5.0 (Linux; Android 14) Chrome/120", "standalone": False}}
    path.write_text(json.dumps(line) + "\n")
    report = client.get(f"/api/v1/assemblies/{assembly['id']}/device-report")
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["sessions"] == 1 and body["phones"][0]["family"] == "Android Chrome"
    assert body["phones"][0]["session_id"] == session_id and body["phones"][0]["slot"] == joined["slot"]
    text = client.get(f"/api/v1/assemblies/{assembly['id']}/device-report?format=text")
    assert text.status_code == 200 and "Android Chrome" in text.text
    assert client.get(f"/api/v1/assemblies/{assembly['id']}/device-report?format=xml").status_code == 422


def test_expired_sessions_and_spent_codes_are_cleaned_after_seven_days(client, settings_env):
    assembly = _assembly(client)
    client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/start")
    idle = _join(client, assembly["invites"][0]["url"], ip="10.20.0.2")
    recorder = _join(client, assembly["invites"][1]["url"], ip="10.20.0.3")
    card = client.post("/api/v1/public/recorder/capabilities", json={"purpose": "ADD_RECORDER_TO_TABLE"},
                       headers={"Authorization": f"Bearer {idle['session_token']}"}).json()
    _join(client, card["url"], ip="10.20.0.4")
    started = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": assembly["rounds"][0]["id"], "mime_type": "audio/webm"},
        headers={"Authorization": f"Bearer {recorder['session_token']}"},
    )
    assert started.status_code == 201, started.text
    with session_scope() as session:
        sessions = session.execute(
            select(RecorderSession).where(RecorderSession.assembly_id == assembly["id"])
        ).scalars().all()
        assert len(sessions) == 3
        long_ago = utcnow() - timedelta(days=8)
        for row in sessions:
            row.expires_at = long_ago
        for invite in session.execute(
            select(RecorderInvite).where(RecorderInvite.assembly_id == assembly["id"])
        ).scalars():
            if invite.single_use:
                invite.consumed_at = long_ago
        idle_id = next(r.id for r in sessions if r.table_number == 1 and r.slot == 1)
    log = device_log_path(settings_env.app_persistent_storage, idle_id)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("{}\n")

    assert sweep.sweep_expired_sessions() == 3  # two idle sessions + the spent code
    assert not log.exists()
    with session_scope() as session:
        left = session.execute(
            select(RecorderSession).where(RecorderSession.assembly_id == assembly["id"])
        ).scalars().all()
        assert [r.table_number for r in left] == [2], "the session with a recording stays"
        recording = session.execute(
            select(Recording).where(Recording.assembly_id == assembly["id"])
        ).scalar_one()
        assert recording.recorder_session_id == left[0].id
        assert not any(
            i.single_use for i in session.execute(
                select(RecorderInvite).where(RecorderInvite.assembly_id == assembly["id"])
            ).scalars()
        )
    assert sweep.sweep_expired_sessions() == 0


def test_a_fresh_expired_session_is_kept_for_a_week(client):
    assembly = _assembly(client)
    _join(client, assembly["invites"][0]["url"], ip="10.20.0.5")
    with session_scope() as session:
        row = session.execute(
            select(RecorderSession).where(RecorderSession.assembly_id == assembly["id"])
        ).scalar_one()
        row.expires_at = utcnow() - timedelta(days=2)
    assert sweep.sweep_expired_sessions() == 0


def test_a_failed_synthesis_shows_on_the_progress_route(client):
    assembly = _assembly(client)
    with session_scope() as session:
        session.add(AppJob(
            type="ANALYZE_ASSEMBLY", payload_json=json.dumps({"assembly_id": assembly["id"]}),
            state="FAILED", attempts=3, max_attempts=3, last_error="HTTP 401 from the model",
        ))
        session.add(AppJob(
            type="ANALYZE_ROUND", payload_json=json.dumps({"round_id": assembly["rounds"][0]["id"]}),
            state="SUCCEEDED", attempts=1, max_attempts=3,
        ))
    progress = client.get(f"/api/v1/assemblies/{assembly['id']}/progress").json()
    assert progress["failures"]["synthesis"]["state"] == "FAILED"
    assert "401" in progress["failures"]["synthesis"]["failure_detail"]
    assert progress["failures"]["rounds"] == {}
