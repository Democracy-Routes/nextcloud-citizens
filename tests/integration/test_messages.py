# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organizer → tables messages (0.7): "5 minutes left" reaches every phone of
the session through its status poll, a targeted message reaches one table,
the phone's receipt shows up as delivered on the Live tab, and nothing leaks
across events."""

import re

from sqlalchemy import select

from citizens.db.models import AuditEvent
from citizens.db.session import session_scope


def _assembly(client, name="TEST Messages", language="en", tables=2):
    created = client.post(
        "/api/v1/assemblies",
        json={
            "name": name,
            "language": language,
            "default_table_count": tables,
            "rounds": [{"title": "R1", "question": "Q"}, {"title": "R2", "question": "Q"}],
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


def test_a_message_reaches_every_table_and_a_receipt_shows_as_delivered(client):
    assembly = _assembly(client)
    round_id = assembly["rounds"][0]["id"]
    table1 = _phone(client, assembly, 0, "10.7.0.1")
    table2 = _phone(client, assembly, 1, "10.7.0.2")
    assert _status(client, table1)["messages"] == []

    sent = client.post(
        f"/api/v1/rounds/{round_id}/messages", json={"kind": "TIME_LEFT", "minutes": 5}
    )
    assert sent.status_code == 201, sent.text
    message = sent.json()
    assert message["text"] == "5 minutes left"
    assert (message["seen_by"], message["not_seen_by"]) == ([], [1, 2])

    for headers in (table1, table2):
        shown = _status(client, headers)["messages"]
        assert [m["text"] for m in shown] == ["5 minutes left"]
        assert shown[0]["id"] == message["id"]

    # table 1 shows it and says so; table 2 is still to come
    seen = client.post(
        "/api/v1/public/recorder/messages/seen", json={"message_id": message["id"]}, headers=table1
    )
    assert seen.status_code == 200, seen.text
    assert _status(client, table1)["messages"] == []
    assert [m["text"] for m in _status(client, table2)["messages"]] == ["5 minutes left"]

    listed = client.get(f"/api/v1/rounds/{round_id}/messages").json()
    assert len(listed) == 1
    assert (listed[0]["seen_by"], listed[0]["not_seen_by"]) == ([1], [2])

    # a receipt never moves backwards and never names another event's message
    assert client.post(
        "/api/v1/public/recorder/messages/seen", json={"message_id": 999_999}, headers=table1
    ).status_code == 404

    with session_scope() as session:
        audit = session.execute(
            select(AuditEvent).where(AuditEvent.event == "message_sent")
        ).scalars().all()
    assert len(audit) == 1 and audit[0].object_id == round_id


def test_a_targeted_message_reaches_one_table_only(client):
    assembly = _assembly(client, language="it")
    round_id = assembly["rounds"][0]["id"]
    table1 = _phone(client, assembly, 0, "10.7.1.1")
    table2 = _phone(client, assembly, 1, "10.7.1.2")

    sent = client.post(
        f"/api/v1/rounds/{round_id}/messages",
        json={"kind": "WRAP_UP", "target_table_number": 2, "sound": True},
    ).json()
    assert sent["text"].startswith("Concludete")
    assert sent["not_seen_by"] == [2]
    assert _status(client, table1)["messages"] == []
    shown = _status(client, table2)["messages"]
    assert [(m["kind"], m["sound"]) for m in shown] == [("WRAP_UP", True)]

    # a table the session does not have
    assert client.post(
        f"/api/v1/rounds/{round_id}/messages", json={"kind": "CUSTOM", "text": "x", "target_table_number": 9}
    ).status_code == 404
    # presets need their number, free text needs text
    url = f"/api/v1/rounds/{round_id}/messages"
    assert client.post(url, json={"kind": "TIME_LEFT"}).status_code == 422
    assert client.post(url, json={"kind": "PROMPT", "text": "  "}).status_code == 422
    one = client.post(url, json={"kind": "TIME_LEFT", "minutes": 1}).json()
    assert one["text"] == "1 minuto rimasto"


def test_messages_stay_inside_their_event(client):
    assembly = _assembly(client)
    round_id = assembly["rounds"][0]["id"]
    client.post(f"/api/v1/rounds/{round_id}/messages", json={"kind": "CUSTOM", "text": "Only here"})

    # another organizer cannot read or write this session's messages
    someone_else = {"X-Test-User": "someone-else"}
    assert client.get(f"/api/v1/rounds/{round_id}/messages", headers=someone_else).status_code == 404
    assert client.post(
        f"/api/v1/rounds/{round_id}/messages", json={"kind": "WRAP_UP"}, headers=someone_else
    ).status_code == 404

    # a phone of another event sees nothing of it
    elsewhere = _assembly(client, name="TEST Elsewhere")
    stranger = _phone(client, elsewhere, 0, "10.7.2.1")
    assert _status(client, stranger)["messages"] == []
    assert client.post(
        "/api/v1/public/recorder/messages/seen", json={"message_id": 1}, headers=stranger
    ).status_code == 404
