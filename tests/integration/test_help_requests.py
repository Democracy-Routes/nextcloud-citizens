# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A table raises its hand (0.7): the request reaches the Live tab as a
readiness warning with the kind of help, the organizer acknowledges it, the
phone learns that on its status poll; one open request per table; nothing
crosses events."""

import re


def _assembly(client, name="TEST Help"):
    created = client.post(
        "/api/v1/assemblies",
        json={
            "name": name,
            "default_table_count": 2,
            "rounds": [{"title": "R1", "question": "Q"}],
        },
    ).json()
    client.post(f"/api/v1/rounds/{created['rounds'][0]['id']}/start")
    return created


def _phone(client, assembly, index, ip):
    token = re.search(r"#/join/(.+)$", assembly["invites"][index]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Forwarded-For": ip}
    ).json()
    return {"Authorization": f"Bearer {joined['session_token']}"}


def _status(client, headers):
    return client.get("/api/v1/public/recorder/status", headers=headers).json()


def _monitor_table(client, round_id, number):
    monitor = client.get(f"/api/v1/rounds/{round_id}/monitor").json()
    return next(t for t in monitor["tables"] if t["number"] == number)


def test_a_hand_goes_up_reaches_the_live_tab_and_comes_down_when_acknowledged(client):
    assembly = _assembly(client)
    round_id = assembly["rounds"][0]["id"]
    table1 = _phone(client, assembly, 0, "10.8.0.1")
    assert _status(client, table1)["help"] is None

    raised = client.post("/api/v1/public/recorder/help", json={"kind": "TECHNICAL"}, headers=table1)
    assert raised.status_code == 201, raised.text
    request = raised.json()
    assert (request["table_number"], request["kind"], request["acknowledged_at"]) == (1, "TECHNICAL", None)

    # the phone sees its own hand; the Live tab sees a warning with the kind
    assert _status(client, table1)["help"]["kind"] == "TECHNICAL"
    row = _monitor_table(client, round_id, 1)
    assert row["help_request"]["id"] == request["id"]
    assert row["readiness"]["status"] == "BLOCKED"  # no phone heartbeat yet, as before
    assert {"code": "HELP_REQUESTED", "severity": "warning", "slot": None, "data": {"kind": "TECHNICAL"}} in (
        row["readiness"]["reasons"]
    )
    assert _monitor_table(client, round_id, 2)["help_request"] is None

    # tapping again changes what the table asks for, it does not queue
    again = client.post("/api/v1/public/recorder/help", json={"kind": "ORGANIZER"}, headers=table1).json()
    assert again["id"] == request["id"] and again["kind"] == "ORGANIZER"

    # the organizer acknowledges: the row is calm again, the phone is told
    ack = client.post(f"/api/v1/help-requests/{request['id']}/acknowledge")
    assert ack.status_code == 200, ack.text
    assert ack.json()["acknowledged_at"] is not None
    row = _monitor_table(client, round_id, 1)
    assert row["help_request"] is None
    assert not any(r["code"] == "HELP_REQUESTED" for r in row["readiness"]["reasons"])
    shown = _status(client, table1)["help"]
    assert shown["id"] == request["id"] and shown["acknowledged_at"] is not None

    # a new tap after acknowledgement is a new hand
    fresh = client.post("/api/v1/public/recorder/help", json={"kind": "PROCESS"}, headers=table1).json()
    assert fresh["id"] != request["id"]
    coffee = client.post("/api/v1/public/recorder/help", json={"kind": "COFFEE"}, headers=table1)
    assert coffee.status_code == 422


def test_a_spontaneous_session_has_nobody_to_call(client):
    made = client.post("/api/v1/sessions", json={"question": "Q", "recording_mode": "independent"}).json()
    token = re.search(r"#/join/(.+)$", made["invites"][0]["url"]).group(1)
    joined = client.post("/api/v1/public/join", json={"token": token},
                         headers={"X-Forwarded-For": "10.8.3.1"}).json()
    headers = {"Authorization": f"Bearer {joined['session_token']}"}
    refused = client.post("/api/v1/public/recorder/help", json={"kind": "TECHNICAL"}, headers=headers)
    assert refused.status_code == 409, refused.text
    assert _status(client, headers)["help"] is None


def test_help_requests_stay_inside_their_event(client):
    assembly = _assembly(client)
    table1 = _phone(client, assembly, 0, "10.8.1.1")
    request = client.post("/api/v1/public/recorder/help", json={"kind": "TECHNICAL"}, headers=table1).json()

    someone_else = {"X-Test-User": "someone-else"}
    assert client.post(
        f"/api/v1/help-requests/{request['id']}/acknowledge", headers=someone_else
    ).status_code == 404

    elsewhere = _assembly(client, name="TEST Elsewhere")
    stranger = _phone(client, elsewhere, 0, "10.8.2.1")
    assert _status(client, stranger)["help"] is None
    assert _monitor_table(client, elsewhere["rounds"][0]["id"], 1)["help_request"] is None
