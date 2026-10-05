# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Table readiness over the API: from heartbeats to READY / NEEDS_ATTENTION / BLOCKED."""

import re
from datetime import timedelta

from sqlalchemy import select

from citizens.db.models import RecorderSession
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope


def _assembly(client, tables=2):
    assembly = client.post(
        "/api/v1/assemblies",
        json={"name": "TEST readiness", "default_table_count": tables,
              "rounds": [{"title": "R1", "question": "Q", "duration_minutes": 30}]},
    ).json()
    return assembly, assembly["rounds"][0]["id"]


def _join(client, url, ip):
    token = re.search(r"#/join/(.+)$", url).group(1)
    body = client.post("/api/v1/public/join", json={"token": token},
                       headers={"X-Forwarded-For": ip}).json()
    return {"Authorization": f"Bearer {body['session_token']}"}


def _heartbeat(client, headers, **fields):
    payload = {"recording_active": False, "local_chunks": 0, "acked_chunks": 0, "storage_ok": True}
    payload.update(fields)
    assert client.post("/api/v1/public/recorder/heartbeat", json=payload, headers=headers).status_code == 200


def _readiness(client, round_id):
    response = client.get(f"/api/v1/rounds/{round_id}/readiness")
    assert response.status_code == 200, response.text
    return response.json()


def test_tables_without_a_phone_are_blocked_and_a_heartbeating_phone_is_ready(client):
    assembly, round_id = _assembly(client)
    before = _readiness(client, round_id)
    assert before["status"] == "BLOCKED" and before["blocked"] == 2
    assert all(t["status"] == "BLOCKED" for t in before["tables"])
    assert before["tables"][0]["reasons"] == [
        {"code": "NO_RECORDER", "severity": "blocker", "slot": None, "data": {}},
    ]

    phone = _join(client, assembly["invites"][0]["url"], "10.9.0.1")
    _heartbeat(client, phone, storage_free_mb=900, battery_level=0.9)
    after = _readiness(client, round_id)
    [table1, table2] = sorted(after["tables"], key=lambda t: t["number"])
    assert table1["status"] == "READY" and table1["reasons"] == []
    assert table1["color_key"] == "blue" and table1["recorders"] == 1
    assert table2["status"] == "BLOCKED"
    assert (after["status"], after["ready"], after["blocked"]) == ("BLOCKED", 1, 1)
    # the monitor carries the same judgement per table
    monitor = client.get(f"/api/v1/rounds/{round_id}/monitor").json()
    assert monitor["readiness"] == {"status": "BLOCKED", "ready": 1, "needs_attention": 0, "blocked": 1}
    assert next(t for t in monitor["tables"] if t["number"] == 1)["readiness"]["status"] == "READY"


def test_low_battery_needs_attention_and_a_silent_sole_phone_blocks(client):
    assembly, round_id = _assembly(client, tables=1)
    phone = _join(client, assembly["invites"][0]["url"], "10.9.0.1")
    _heartbeat(client, phone, battery_level=0.1, storage_free_mb=50)
    [table] = _readiness(client, round_id)["tables"]
    assert table["status"] == "NEEDS_ATTENTION"
    assert sorted(r["code"] for r in table["reasons"]) == ["LOW_BATTERY", "LOW_STORAGE"]
    assert all(r["severity"] == "warning" and r["slot"] == 1 for r in table["reasons"])

    # the phone stops answering
    with session_scope() as session:
        for recorder_session in session.execute(
            select(RecorderSession).where(RecorderSession.assembly_id == assembly["id"])
        ).scalars():
            recorder_session.last_status_at = utcnow() - timedelta(minutes=5)
    [table] = _readiness(client, round_id)["tables"]
    assert table["status"] == "BLOCKED"
    assert [(r["code"], r["severity"]) for r in table["reasons"]] == [("RECORDER_OFFLINE", "blocker")]
    assert table["reasons"][0]["data"]["seconds_since_contact"] >= 299


def test_a_backup_recorder_keeps_a_table_runnable_when_the_first_phone_goes_quiet(client):
    assembly, round_id = _assembly(client, tables=1)
    phone_a = _join(client, assembly["invites"][0]["url"], "10.9.0.1")
    card = client.post("/api/v1/public/recorder/capabilities",
                       json={"purpose": "ADD_RECORDER_TO_TABLE"}, headers=phone_a).json()
    phone_b = _join(client, card["url"], "10.9.0.2")
    _heartbeat(client, phone_a)
    _heartbeat(client, phone_b)
    [table] = _readiness(client, round_id)["tables"]
    assert table["status"] == "READY" and table["recorders"] == 2

    with session_scope() as session:
        first = session.execute(
            select(RecorderSession).where(RecorderSession.assembly_id == assembly["id"],
                                          RecorderSession.slot == 1)
        ).scalar_one()
        first.last_status_at = utcnow() - timedelta(minutes=5)
    [table] = _readiness(client, round_id)["tables"]
    assert table["status"] == "NEEDS_ATTENTION"
    assert [(r["code"], r["severity"], r["slot"]) for r in table["reasons"]] == [
        ("RECORDER_OFFLINE", "warning", 1),
    ]


def test_readiness_is_private_to_the_owner(client):
    _, round_id = _assembly(client, tables=1)
    assert client.get(f"/api/v1/rounds/{round_id}/readiness",
                      headers={"X-Test-User": "someone-else"}).status_code == 404
