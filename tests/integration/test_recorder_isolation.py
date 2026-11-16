# SPDX-FileCopyrightText: 2026 Alessandro Oppo
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A recorder session must reach ONLY its own table's data.

The code is correct today — every public route resolves the recording through
`get_session_recording`, which checks assembly AND table number. But the whole
suite had only three cross-user assertions, so nothing stopped a refactor
quietly widening that. These are the negative tests: each one asserts a request
that must NOT succeed.

A phone's bearer token is the only thing standing between a room full of
strangers and every other table's audio, so this is worth guarding explicitly.
"""

import re

import pytest


def _assembly(client, name, tables=2):
    """An assembly with its round already started — orchestrated mode refuses
    recordings until the facilitator opens the round."""
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": name,
            "default_table_count": tables,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()
    client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/start")
    return assembly


def _join(client, assembly, index, invites=None):
    """Join as one table and return its bearer headers."""
    if invites is None:
        invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[index]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Origin-IP": "203.0.113.7"}
    )
    assert joined.status_code == 200, joined.text
    data = joined.json()
    return {"Authorization": f"Bearer {data['session_token']}"}, data


def _start(client, headers, round_id):
    response = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": round_id, "mime_type": "audio/webm;codecs=opus"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["recording_id"]


@pytest.fixture
def two_tables(client):
    """One assembly, two tables, each with its own recording."""
    assembly = _assembly(client, "TEST Isolation", tables=2)
    # one sheet of codes, two tables — regenerating per table would revoke the
    # first table's invite and quietly change what is being tested
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    headers_a, data_a = _join(client, assembly, 0, invites)
    headers_b, _ = _join(client, assembly, 1, invites)
    round_id = data_a["rounds"][0]["id"]
    return {
        "client": client,
        "assembly": assembly,
        "round_id": round_id,
        "a": (headers_a, _start(client, headers_a, round_id)),
        "b": (headers_b, _start(client, headers_b, round_id)),
    }


def test_a_table_cannot_read_another_tables_recording(two_tables):
    client = two_tables["client"]
    headers_a, _ = two_tables["a"]
    _, recording_b = two_tables["b"]

    denied = client.get(f"/api/v1/public/recorder/recordings/{recording_b}", headers=headers_a)
    assert denied.status_code == 404, "table A read table B's recording"


def test_a_table_cannot_upload_into_another_tables_recording(two_tables):
    """The one that would corrupt the record: audio attributed to the wrong table."""
    import hashlib

    client = two_tables["client"]
    headers_a, _ = two_tables["a"]
    _, recording_b = two_tables["b"]
    blob = b"not-this-tables-audio"

    denied = client.post(
        f"/api/v1/public/recorder/recordings/{recording_b}/chunks/0",
        content=blob,
        headers={
            **headers_a,
            "Content-Type": "application/octet-stream",
            "X-Chunk-SHA256": hashlib.sha256(blob).hexdigest(),
        },
    )
    assert denied.status_code == 404, "table A wrote audio into table B's recording"


def test_a_table_cannot_complete_another_tables_recording(two_tables):
    client = two_tables["client"]
    headers_a, _ = two_tables["a"]
    _, recording_b = two_tables["b"]

    denied = client.post(
        f"/api/v1/public/recorder/recordings/{recording_b}/complete",
        json={"total_chunks": 1},
        headers=headers_a,
    )
    assert denied.status_code == 404


def test_a_table_cannot_read_another_tables_captions(two_tables):
    client = two_tables["client"]
    headers_a, _ = two_tables["a"]
    _, recording_b = two_tables["b"]

    denied = client.get(
        f"/api/v1/public/recorder/recordings/{recording_b}/live", headers=headers_a
    )
    assert denied.status_code == 404


def test_a_token_from_one_assembly_cannot_touch_another(client):
    """Cross-assembly is the worst case: a different event entirely."""
    first = _assembly(client, "TEST Isolation One")
    second = _assembly(client, "TEST Isolation Two")
    headers_first, data_first = _join(client, first, 0)
    headers_second, data_second = _join(client, second, 0)
    recording_second = _start(client, headers_second, data_second["rounds"][0]["id"])

    denied = client.get(
        f"/api/v1/public/recorder/recordings/{recording_second}", headers=headers_first
    )
    assert denied.status_code == 404, "a token from one assembly reached another's recording"

    # and it cannot start a recording against the other assembly's round either
    wrong_round = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": data_second["rounds"][0]["id"], "mime_type": "audio/webm"},
        headers=headers_first,
    )
    assert wrong_round.status_code == 404


def test_fabricated_identifiers_are_refused(two_tables):
    client = two_tables["client"]
    headers_a, _ = two_tables["a"]
    made_up = "00000000-0000-4000-8000-000000000000"

    assert client.get(
        f"/api/v1/public/recorder/recordings/{made_up}", headers=headers_a
    ).status_code == 404
    assert client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": made_up, "mime_type": "audio/webm"},
        headers=headers_a,
    ).status_code == 404


def test_a_revoked_invite_kills_the_session(two_tables):
    """Revoke must disconnect devices already joined, not only stop new joins."""
    client = two_tables["client"]
    headers_a, _ = two_tables["a"]
    assembly_id = two_tables["assembly"]["id"]

    assert client.get("/api/v1/public/recorder/status", headers=headers_a).status_code == 200
    assert client.post(f"/api/v1/assemblies/{assembly_id}/invites/revoke").status_code == 204
    assert client.get("/api/v1/public/recorder/status", headers=headers_a).status_code == 401


def test_revoke_reaches_sessions_from_superseded_invites(client):
    """Revoke after a regeneration must still cut the tables that are recording.

    Regenerating the QR sheet marks the old invites revoked while deliberately
    leaving live tables connected. Scoping revoke to *currently active* invites
    therefore skipped exactly those phones — the organizer hit the emergency
    stop and the devices already in the room kept their bearer.
    """
    assembly = _assembly(client, "TEST Isolation Regen")
    headers, _ = _join(client, assembly, 0)
    assert client.get("/api/v1/public/recorder/status", headers=headers).status_code == 200

    # new sheet printed mid-event; the table already recording must not be kicked
    client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate")
    assert client.get("/api/v1/public/recorder/status", headers=headers).status_code == 200

    assert client.post(f"/api/v1/assemblies/{assembly['id']}/invites/revoke").status_code == 204
    assert client.get("/api/v1/public/recorder/status", headers=headers).status_code == 401


def test_a_fabricated_bearer_is_refused(client):
    assembly = _assembly(client, "TEST Isolation Bearer")
    _join(client, assembly, 0)
    for bearer in ("", "not-a-token", "Bearer", "x" * 43):
        response = client.get(
            "/api/v1/public/recorder/status", headers={"Authorization": f"Bearer {bearer}"}
        )
        assert response.status_code == 401, f"accepted bearer {bearer!r}"


def test_revoking_all_invites_cuts_a_facilitator_session(two_tables):
    client = two_tables["client"]
    assembly = two_tables["assembly"]
    headers_b, _ = two_tables["b"]
    card = client.post(
        "/api/v1/public/recorder/capabilities", json={"purpose": "FACILITATE_TABLE"}, headers=headers_b
    )
    assert card.status_code == 201, card.text
    token = re.search(r"#/facilitate/(.+)$", card.json()["url"]).group(1)
    joined = client.post(
        "/api/v1/public/facilitate", json={"token": token}, headers={"X-Forwarded-For": "10.30.0.9"}
    )
    assert joined.status_code == 200, joined.text
    facilitator = {"Authorization": f"Bearer {joined.json()['facilitator_token']}"}
    assert client.get("/api/v1/public/facilitator/status", headers=facilitator).status_code == 200

    assert client.post(f"/api/v1/assemblies/{assembly['id']}/invites/revoke").status_code == 204
    assert client.get("/api/v1/public/facilitator/status", headers=facilitator).status_code == 401
    assert client.post(
        "/api/v1/public/facilitator/codes", json={"purpose": "ADD_RECORDER_TO_TABLE"},
        headers=facilitator,
    ).status_code == 401
