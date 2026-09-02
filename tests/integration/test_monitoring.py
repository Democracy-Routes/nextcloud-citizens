# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Round lifecycle, device heartbeats → facilitator monitor, client log shipping."""

import re


def _setup(client):
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Monitor",
            "default_table_count": 2,
            "rounds": [
                {"title": "R1", "question": "Q1", "duration_minutes": 30},
                {"title": "R2", "question": "Q2", "duration_minutes": 30},
            ],
        },
    ).json()
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Forwarded-For": "10.2.2.2"}
    ).json()
    return assembly, {"Authorization": f"Bearer {joined['session_token']}"}


def test_round_lifecycle(client):
    assembly, _ = _setup(client)
    round1, round2 = assembly["rounds"]

    assert client.post(f"/api/v1/rounds/{round1['id']}/start").json()["status"] == "ACTIVE"
    # only one active round at a time
    assert client.post(f"/api/v1/rounds/{round2['id']}/start").status_code == 409
    # cannot end a round that is not active
    assert client.post(f"/api/v1/rounds/{round2['id']}/end").status_code == 409

    assert client.post(f"/api/v1/rounds/{round1['id']}/end").json()["status"] == "ENDED"
    assert client.post(f"/api/v1/rounds/{round2['id']}/start").json()["status"] == "ACTIVE"

    # recorder sees round states via public status
    detail = client.get(f"/api/v1/assemblies/{assembly['id']}").json()
    assert [r["status"] for r in detail["rounds"]] == ["ENDED", "ACTIVE"]


def test_heartbeat_feeds_monitor(client):
    assembly, recorder_headers = _setup(client)
    round1 = assembly["rounds"][0]

    monitor = client.get(f"/api/v1/rounds/{round1['id']}/monitor").json()
    table1 = next(t for t in monitor["tables"] if t["number"] == 1)
    assert table1["device"]["connected"] is False
    assert table1["local_recording_safe"] is False

    heartbeat = client.post(
        "/api/v1/public/recorder/heartbeat",
        json={
            "recording_active": True,
            "local_chunks": 12,
            "acked_chunks": 10,
            "storage_ok": True,
            "storage_free_mb": 512.5,
        },
        headers=recorder_headers,
    )
    assert heartbeat.status_code == 200

    monitor = client.get(f"/api/v1/rounds/{round1['id']}/monitor").json()
    table1 = next(t for t in monitor["tables"] if t["number"] == 1)
    assert table1["device"]["connected"] is True
    assert table1["device"]["status"]["local_chunks"] == 12
    assert table1["local_recording_safe"] is True

    # a device reporting storage failure is never claimed safe
    client.post(
        "/api/v1/public/recorder/heartbeat",
        json={"recording_active": True, "storage_ok": False},
        headers=recorder_headers,
    )
    monitor = client.get(f"/api/v1/rounds/{round1['id']}/monitor").json()
    table1 = next(t for t in monitor["tables"] if t["number"] == 1)
    assert table1["local_recording_safe"] is False


def test_device_log_shipping(client, settings_env):
    assembly, recorder_headers = _setup(client)

    shipped = client.post(
        "/api/v1/public/recorder/logs",
        json={
            "entries": [
                {"ts": 1_700_000_000.0, "level": "info", "event": "chunk_saved", "data": {"seq": 0}},
                {"ts": 1_700_000_010.0, "level": "warn", "event": "upload_failed"},
            ]
        },
        headers=recorder_headers,
    )
    assert shipped.status_code == 200
    assert shipped.json()["accepted"] == 2

    logs = client.get(f"/api/v1/assemblies/{assembly['id']}/tables/1/device-logs").json()
    assert logs["session_id"] is not None
    assert len(logs["lines"]) == 2
    assert "chunk_saved" in logs["lines"][0]

    # other users cannot read device logs of an assembly they don't own
    other = client.get(
        f"/api/v1/assemblies/{assembly['id']}/tables/1/device-logs",
        headers={"X-Test-User": "intruder"},
    )
    assert other.status_code == 404


def test_the_monitor_reports_every_round_status(client):
    """The Live tab polls this every few seconds but used to compute "which
    round is next" from the assembly object it was handed on mount, which
    nothing refreshed — so it could offer to start a round the server had
    already started. One request now answers both questions."""
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Monitor Rounds",
            "default_table_count": 1,
            "rounds": [
                {"title": "R1", "question": "Q1?", "duration_minutes": 30},
                {"title": "R2", "question": "Q2?", "duration_minutes": 30},
            ],
        },
    ).json()
    first, second = assembly["rounds"]
    client.post(f"/api/v1/rounds/{first['id']}/start")
    client.post(f"/api/v1/rounds/{first['id']}/end")
    client.post(f"/api/v1/rounds/{second['id']}/start")

    monitor = client.get(f"/api/v1/rounds/{first['id']}/monitor").json()

    assert "rounds" in monitor, "the monitor does not report the other rounds"
    by_id = {r["id"]: r for r in monitor["rounds"]}
    assert by_id[second["id"]]["status"] == "ACTIVE", (
        "the monitor still reports round 2 as available to start, which is how "
        "the Live tab offered a round that was already running"
    )
    assert [r["position"] for r in monitor["rounds"]] == [1, 2]


def test_the_heartbeat_carries_the_phones_battery(client):
    """Everything else about a dying phone is recovery; this is the only signal
    that arrives while there is still time to swap it."""
    import re

    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Battery",
            "default_table_count": 1,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()
    round_id = assembly["rounds"][0]["id"]
    client.post(f"/api/v1/rounds/{round_id}/start")
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Origin-IP": "203.0.113.7"}
    ).json()
    headers = {"Authorization": f"Bearer {joined['session_token']}"}

    beat = client.post(
        "/api/v1/public/recorder/heartbeat",
        json={"recording_active": True, "storage_ok": True, "battery_level": 0.07},
        headers=headers,
    )
    assert beat.status_code == 200, beat.text

    monitor = client.get(f"/api/v1/rounds/{round_id}/monitor").json()
    assert monitor["tables"][0]["device"]["status"]["battery_level"] == 0.07


def test_an_impossible_battery_level_is_refused(client):
    """The value is displayed as a percentage; a client must not be able to put
    nonsense on the organizer's screen."""
    import re

    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Battery Range",
            "default_table_count": 1,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()
    client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/start")
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Origin-IP": "203.0.113.7"}
    ).json()
    headers = {"Authorization": f"Bearer {joined['session_token']}"}

    refused = client.post(
        "/api/v1/public/recorder/heartbeat",
        json={"recording_active": True, "storage_ok": True, "battery_level": 7},
        headers=headers,
    )
    assert refused.status_code == 422
