# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The phone that already joined decides what the next QR code means.

ADD_RECORDER_TO_TABLE and ADD_TABLE are made by a joined phone, shown as a code,
and scanned by the next phone — which follows the code and never picks a role.
They are short-lived, single-use and server-enforced, and they share the row,
token mechanism and join route with the printed table codes, which stay
reusable.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import select

from citizens.db.models import AuditEvent, RecorderInvite
from citizens.db.session import session_scope
from citizens.services import capabilities


def _assembly(client, tables=2, rounds=2, mode="orchestrated"):
    created = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST capabilities",
            "default_table_count": tables,
            "recording_mode": mode,
            "rounds": [{"title": f"R{i}", "question": "Q"} for i in range(1, rounds + 1)],
        },
    ).json()
    client.post(f"/api/v1/rounds/{created['rounds'][0]['id']}/start")
    return created


def _token(url):
    return re.search(r"#/join/(.+)$", url).group(1)


def _join(client, url, ip="10.5.0.1"):
    return client.post(
        "/api/v1/public/join", json={"token": _token(url)}, headers={"X-Forwarded-For": ip}
    )


def _auth(joined):
    return {"Authorization": f"Bearer {joined['session_token']}"}


def _capability(client, headers, purpose, round_id=None):
    response = client.post(
        "/api/v1/public/recorder/capabilities",
        json={"purpose": purpose, "round_id": round_id},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_the_printed_table_code_stays_reusable_and_is_slot_one(client):
    assembly = _assembly(client)
    first = _join(client, assembly["invites"][0]["url"]).json()
    second = _join(client, assembly["invites"][0]["url"], ip="10.5.0.2").json()
    assert first["joined"]["purpose"] == "JOIN_TABLE"
    assert (first["slot"], second["slot"]) == (1, 1)
    assert first["joined"]["table_created"] is False


def test_add_recorder_joins_the_intended_table_in_the_next_slot_and_nothing_else(client):
    assembly = _assembly(client)
    phone_a = _join(client, assembly["invites"][0]["url"]).json()

    card = _capability(client, _auth(phone_a), "ADD_RECORDER_TO_TABLE")
    assert card["purpose"] == "ADD_RECORDER_TO_TABLE"
    assert card["table_number"] == 1 and card["color_key"] == "blue"
    assert "#/join/" in card["url"] and card["qr_svg"].startswith("<svg")

    phone_b = _join(client, card["url"], ip="10.5.0.3")
    assert phone_b.status_code == 200, phone_b.text
    body = phone_b.json()
    assert body["table_number"] == 1
    assert body["joined"] == {
        "purpose": "ADD_RECORDER_TO_TABLE", "table_number": 1, "color_key": "blue",
        "slot": 2, "table_created": False,
    }
    # no table was created, and the printed codes are untouched
    numbers = [t["number"] for t in client.get(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/tables").json()]
    assert numbers == [1, 2]
    invites = client.get(f"/api/v1/assemblies/{assembly['id']}/invites").json()
    assert sorted(i["table_number"] for i in invites) == [1, 2]
    links = client.get(f"/api/v1/assemblies/{assembly['id']}/invites/links").json()
    assert sorted(card["table_number"] for card in links) == [1, 2]

    # a third recorder takes slot 3; slots are never reused
    card2 = _capability(client, _auth(phone_a), "ADD_RECORDER_TO_TABLE")
    assert _join(client, card2["url"], ip="10.5.0.4").json()["slot"] == 3


def test_an_action_code_is_single_use(client):
    assembly = _assembly(client)
    phone_a = _join(client, assembly["invites"][0]["url"]).json()
    card = _capability(client, _auth(phone_a), "ADD_RECORDER_TO_TABLE")

    assert _join(client, card["url"], ip="10.5.0.3").status_code == 200
    again = _join(client, card["url"], ip="10.5.0.4")
    assert again.status_code == 410
    assert "already been used" in again.json()["detail"]


def test_add_table_creates_the_next_table_and_the_scanner_is_its_first_recorder(client):
    assembly = _assembly(client)
    round1 = assembly["rounds"][0]
    phone_a = _join(client, assembly["invites"][0]["url"]).json()

    card = _capability(client, _auth(phone_a), "ADD_TABLE", round_id=round1["id"])
    assert card["purpose"] == "ADD_TABLE"
    assert card["table_number"] is None and card["color_key"] is None
    assert card["round_id"] == round1["id"]

    phone_c = _join(client, card["url"], ip="10.5.0.5")
    assert phone_c.status_code == 200, phone_c.text
    body = phone_c.json()
    assert body["joined"] == {
        "purpose": "ADD_TABLE", "table_number": 3, "color_key": "orange",
        "slot": 1, "table_created": True,
    }
    assert body["table_number"] == 3 and body["table_color"] == "orange"

    # the table exists in every round, has its own printed code, and records now
    for round_ in assembly["rounds"]:
        numbers = [t["number"] for t in client.get(f"/api/v1/rounds/{round_['id']}/tables").json()]
        assert numbers == [1, 2, 3]
    invites = client.get(f"/api/v1/assemblies/{assembly['id']}/invites").json()
    assert sorted((i["table_number"], i["active"]) for i in invites) == [(1, True), (2, True), (3, True)]
    started = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": round1["id"], "mime_type": "audio/webm"},
        headers=_auth(body),
    )
    assert started.status_code == 201, started.text

    # a replacement phone for table 3 rescans the table's own code, as for any table
    links = client.get(f"/api/v1/assemblies/{assembly['id']}/invites/links").json()
    [table3] = [card for card in links if card["table_number"] == 3]
    rescan = _join(client, table3["url"], ip="10.5.0.6").json()
    assert (rescan["table_number"], rescan["slot"]) == (3, 1)


def test_two_phones_scanning_one_add_table_code_make_one_table(client):
    assembly = _assembly(client, tables=1, rounds=1)
    phone_a = _join(client, assembly["invites"][0]["url"]).json()
    card = _capability(client, _auth(phone_a), "ADD_TABLE")

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda i: _join(client, card["url"], ip=f"10.5.1.{i}"), range(4)))
    statuses = sorted(r.status_code for r in responses)
    assert statuses == [200, 410, 410, 410], statuses
    numbers = [t["number"] for t in client.get(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/tables").json()]
    assert numbers == [1, 2]


def test_expired_and_revoked_action_codes_are_refused(client, monkeypatch):
    assembly = _assembly(client)
    phone_a = _join(client, assembly["invites"][0]["url"]).json()

    monkeypatch.setattr(capabilities, "CAPABILITY_TTL", timedelta(seconds=-5))
    expired = _capability(client, _auth(phone_a), "ADD_RECORDER_TO_TABLE")
    assert _join(client, expired["url"], ip="10.5.0.7").status_code == 401
    monkeypatch.setattr(capabilities, "CAPABILITY_TTL", timedelta(minutes=15))

    revoked = _capability(client, _auth(phone_a), "ADD_TABLE")
    client.post(f"/api/v1/assemblies/{assembly['id']}/invites/revoke")
    assert _join(client, revoked["url"], ip="10.5.0.8").status_code == 401
    # nothing was created for a refused code
    numbers = [t["number"] for t in client.get(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/tables").json()]
    assert numbers == [1, 2]


def test_what_a_phone_may_not_make(client):
    plenary = _assembly(client, tables=1, rounds=1, mode="plenary")
    room = _join(client, plenary["invites"][0]["url"]).json()
    refused = client.post(
        "/api/v1/public/recorder/capabilities", json={"purpose": "ADD_TABLE"}, headers=_auth(room)
    )
    assert refused.status_code == 409
    # ...but a plenary room may add phones to its one table
    assert _capability(client, _auth(room), "ADD_RECORDER_TO_TABLE")["table_number"] == 1

    assembly = _assembly(client, tables=1, rounds=1)
    phone = _join(client, assembly["invites"][0]["url"], ip="10.5.0.9").json()
    unknown = client.post(
        "/api/v1/public/recorder/capabilities", json={"purpose": "BECOME_FACILITATOR"},
        headers=_auth(phone),
    )
    assert unknown.status_code == 422
    other_round = _assembly(client, tables=1, rounds=1)["rounds"][0]["id"]
    foreign = client.post(
        "/api/v1/public/recorder/capabilities",
        json={"purpose": "ADD_TABLE", "round_id": other_round}, headers=_auth(phone),
    )
    assert foreign.status_code == 404
    client.post(f"/api/v1/assemblies/{assembly['id']}/close")
    closed = client.post(
        "/api/v1/public/recorder/capabilities", json={"purpose": "ADD_TABLE"}, headers=_auth(phone)
    )
    assert closed.status_code == 409


def test_creation_and_consumption_are_audited_without_the_token(client):
    assembly = _assembly(client, tables=1, rounds=1)
    phone_a = _join(client, assembly["invites"][0]["url"]).json()
    card = _capability(client, _auth(phone_a), "ADD_TABLE")
    token = _token(card["url"])
    assert _join(client, card["url"], ip="10.5.0.10").status_code == 200

    with session_scope() as session:
        events = list(
            session.execute(
                select(AuditEvent).where(
                    AuditEvent.event.in_(("capability_created", "capability_consumed"))
                ).order_by(AuditEvent.created_at)
            ).scalars()
        )
        assert [e.event for e in events] == ["capability_created", "capability_consumed"]
        for event in events:
            assert event.object_type == "recorder_invite"
            assert token not in (event.data_json or "")
            assert '"purpose": "ADD_TABLE"' in event.data_json
        invite = session.get(RecorderInvite, events[0].object_id)
        assert invite.single_use and invite.consumed_at is not None
        assert invite.created_by_session_id is not None
