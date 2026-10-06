# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The facilitator's own phone (0.7): the table's phone makes a
FACILITATE_TABLE code, the facilitator scans it and sees one table — the
session's question and time, the roster, the hand, the organizer's messages
— writes a prompt that reaches only that table's phones, raises the table's
hand, and makes codes to register for consent or add this phone as a
recorder. It never records; nothing crosses tables or events."""

import re


def _assembly(client, name="TEST Facilitator", **extra):
    created = client.post(
        "/api/v1/assemblies",
        json={
            "name": name,
            "default_table_count": 2,
            "rounds": [
                {"title": "Problems", "question": "What is broken?", "objective": "A list",
                 "duration_minutes": 20},
                {"title": "Proposals", "question": "What do we propose?"},
            ],
            **extra,
        },
    ).json()
    return created


def _phone(client, assembly, index, ip):
    token = re.search(r"#/join/(.+)$", assembly["invites"][index]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Forwarded-For": ip}
    ).json()
    return {"Authorization": f"Bearer {joined['session_token']}"}


def _facilitator(client, table_headers, ip="10.20.0.9"):
    card = client.post(
        "/api/v1/public/recorder/capabilities", json={"purpose": "FACILITATE_TABLE"},
        headers=table_headers,
    )
    assert card.status_code == 201, card.text
    assert card.json()["purpose"] == "FACILITATE_TABLE" and "#/facilitate/" in card.json()["url"]
    token = re.search(r"#/facilitate/(.+)$", card.json()["url"]).group(1)
    joined = client.post(
        "/api/v1/public/facilitate", json={"token": token}, headers={"X-Forwarded-For": ip}
    )
    assert joined.status_code == 200, joined.text
    return {"Authorization": f"Bearer {joined.json()['facilitator_token']}"}, joined.json(), token


def test_the_facilitator_sees_one_table_and_the_running_session(client):
    assembly = _assembly(client)
    round1, round2 = assembly["rounds"]
    table2 = _phone(client, assembly, 1, "10.20.0.2")
    facilitator, joined, token = _facilitator(client, table2)

    assert joined["table_number"] == 2 and joined["color_key"] == "green"
    assert joined["assembly"]["name"] == "TEST Facilitator"
    # before any session runs: the next one, without a clock
    assert joined["round"]["id"] == round1["id"] and joined["round"]["seconds_left"] is None
    assert joined["speaking"] is None and joined["advice"] == []
    assert joined["capabilities"]["live_speaking_balance"] is False

    client.post(f"/api/v1/rounds/{round1['id']}/start")
    status = client.get("/api/v1/public/facilitator/status", headers=facilitator).json()
    assert status["round"]["status"] == "ACTIVE"
    assert status["round"]["question"] == "What is broken?"
    assert status["round"]["objective"] == "A list"
    assert 19 * 60 < status["round"]["seconds_left"] <= 20 * 60
    assert status["round"]["ends_at"]
    assert [r["position"] for r in status["rounds"]] == [1, 2]
    assert status["consent"]["registered"] == 0 and status["recorders"] == 1
    assert status["help"] is None and status["messages"] == []

    # the code is reusable: a reload rescans it
    again = client.post("/api/v1/public/facilitate", json={"token": token})
    assert again.status_code == 200
    # ...but it never makes a recorder
    as_recorder = client.post("/api/v1/public/join", json={"token": token})
    assert as_recorder.status_code == 409
    peek = client.post("/api/v1/public/capabilities/peek", json={"token": token}).json()
    assert peek["valid"] and peek["purpose"] == "FACILITATE_TABLE" and peek["table_number"] == 2


def test_a_prompt_reaches_only_this_table_and_a_hand_reaches_the_live_tab(client):
    assembly = _assembly(client)
    round_id = assembly["rounds"][0]["id"]
    client.post(f"/api/v1/rounds/{round_id}/start")
    table1 = _phone(client, assembly, 0, "10.20.0.1")
    table2 = _phone(client, assembly, 1, "10.20.0.2")
    facilitator, _, _ = _facilitator(client, table2)

    sent = client.post(
        "/api/v1/public/facilitator/prompt", json={"text": "Has everyone spoken?"},
        headers=facilitator,
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["kind"] == "PROMPT" and sent.json()["sound"] is True

    seen_by_2 = client.get("/api/v1/public/recorder/status", headers=table2).json()["messages"]
    assert [m["text"] for m in seen_by_2] == ["Has everyone spoken?"]
    seen_by_1 = client.get("/api/v1/public/recorder/status", headers=table1).json()["messages"]
    assert seen_by_1 == []
    # the author does not get their own prompt back
    status = client.get("/api/v1/public/facilitator/status", headers=facilitator).json()
    assert status["messages"] == []

    # the organizer's message to every table reaches the facilitator too,
    # once, and the receipt keeps it from coming again
    message = client.post(
        f"/api/v1/rounds/{round_id}/messages", json={"kind": "TIME_LEFT", "minutes": 5}
    ).json()
    status = client.get("/api/v1/public/facilitator/status", headers=facilitator).json()
    assert [m["id"] for m in status["messages"]] == [message["id"]]
    assert client.post(
        "/api/v1/public/facilitator/messages/seen", json={"message_id": message["id"]},
        headers=facilitator,
    ).status_code == 200
    status = client.get("/api/v1/public/facilitator/status", headers=facilitator).json()
    assert status["messages"] == []
    listed = client.get(f"/api/v1/rounds/{round_id}/messages").json()
    assert listed[0]["created_by"].startswith("facilitator:") is False  # organizer's
    assert listed[1]["created_by"].startswith("facilitator:")
    assert listed[1]["target_table_number"] == 2

    # the hand, from the facilitator's phone, is the table's hand
    hand = client.post(
        "/api/v1/public/facilitator/help", json={"kind": "PROCESS"}, headers=facilitator
    )
    assert hand.status_code == 201, hand.text
    monitor = client.get(f"/api/v1/rounds/{round_id}/monitor").json()
    table = next(t for t in monitor["tables"] if t["number"] == 2)
    assert table["help_request"]["kind"] == "PROCESS"
    assert any(r["code"] == "HELP_REQUESTED" for r in table["readiness"]["reasons"])
    assert client.get("/api/v1/public/recorder/status", headers=table2).json()["help"]["kind"] == "PROCESS"
    status = client.get("/api/v1/public/facilitator/status", headers=facilitator).json()
    assert status["help"]["kind"] == "PROCESS" and status["help"]["acknowledged_at"] is None


def test_a_prompt_needs_a_running_session(client):
    assembly = _assembly(client)
    table1 = _phone(client, assembly, 0, "10.20.0.1")
    facilitator, _, _ = _facilitator(client, table1)
    refused = client.post(
        "/api/v1/public/facilitator/prompt", json={"text": "Hello"}, headers=facilitator
    )
    assert refused.status_code == 409


def test_the_facilitator_makes_codes_for_consent_and_a_second_recorder(client):
    assembly = _assembly(client, participant_consent="required")
    round_id = assembly["rounds"][0]["id"]
    client.post(f"/api/v1/rounds/{round_id}/start")
    table1 = _phone(client, assembly, 0, "10.20.0.1")
    facilitator, _, _ = _facilitator(client, table1)

    register = client.post(
        "/api/v1/public/facilitator/codes", json={"purpose": "REGISTER_PARTICIPANT"},
        headers=facilitator,
    )
    assert register.status_code == 201, register.text
    assert register.json()["table_number"] == 1 and "#/register/" in register.json()["url"]
    token = re.search(r"#/register/(.+)$", register.json()["url"]).group(1)
    notice = client.post("/api/v1/public/register/notice", json={"token": token}).json()
    registered = client.post(
        "/api/v1/public/register",
        json={
            "token": token, "name": "Fatima (facilitator)", "notice_hash": notice["hash"],
            "notice_read": True, "recording_consent": True, "transcription_consent": True,
            "analysis_consent": True, "publication_consent": True,
        },
    )
    assert registered.status_code == 201, registered.text
    status = client.get("/api/v1/public/facilitator/status", headers=facilitator).json()
    assert [p["name"] for p in status["participants"]] == ["Fatima (facilitator)"]
    assert status["consent"]["consenting"] == 1

    recorder = client.post(
        "/api/v1/public/facilitator/codes", json={"purpose": "ADD_RECORDER_TO_TABLE"},
        headers=facilitator,
    )
    assert recorder.status_code == 201, recorder.text
    assert "#/join/" in recorder.json()["url"] and recorder.json()["round_id"] == round_id
    join_token = re.search(r"#/join/(.+)$", recorder.json()["url"]).group(1)
    joined = client.post("/api/v1/public/join", json={"token": join_token})
    assert joined.status_code == 200, joined.text
    assert joined.json()["joined"]["purpose"] == "ADD_RECORDER_TO_TABLE"
    assert joined.json()["table_number"] == 1 and joined.json()["joined"]["slot"] == 2
    status = client.get("/api/v1/public/facilitator/status", headers=facilitator).json()
    assert status["recorders"] == 2

    # a code it may not make
    assert client.post(
        "/api/v1/public/facilitator/codes", json={"purpose": "ADD_TABLE"}, headers=facilitator
    ).status_code == 422


def test_leaving_and_closing_end_the_facilitator_session(client):
    assembly = _assembly(client)
    table1 = _phone(client, assembly, 0, "10.20.0.1")
    facilitator, _, token = _facilitator(client, table1)
    assert client.post("/api/v1/public/facilitator/heartbeat", headers=facilitator).status_code == 200
    assert client.post("/api/v1/public/facilitator/leave", headers=facilitator).status_code == 200
    assert client.get("/api/v1/public/facilitator/status", headers=facilitator).status_code == 401

    client.post(f"/api/v1/assemblies/{assembly['id']}/close")
    assert client.post("/api/v1/public/facilitate", json={"token": token}).status_code == 409


def test_a_session_has_no_hand_to_raise_but_still_a_facilitator(client):
    created = client.post("/api/v1/sessions/record-now", json={"language": "en"}).json()
    token = re.search(r"#/join/(.+)$", created["recorder_url"]).group(1)
    joined = client.post("/api/v1/public/join", json={"token": token}).json()
    table = {"Authorization": f"Bearer {joined['session_token']}"}
    facilitator, status, _ = _facilitator(client, table)
    # a Record-now session's round starts when the phone starts recording
    assert status["assembly"]["kind"] == "session" and status["round"]["status"] == "NOT_STARTED"
    refused = client.post(
        "/api/v1/public/facilitator/help", json={"kind": "PROCESS"}, headers=facilitator
    )
    assert refused.status_code == 409
