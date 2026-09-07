# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plenary mode: the whole room recorded by many phones at once.

One group, one shared code, several concurrent devices — the opposite of the
one-phone-per-table model every other mode assumes. These cover the guards that
had to be relaxed and the single-table shape.
"""

import re


def _plenary(client, name="TEST Plenary"):
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": name,
            "recording_mode": "plenary",
            # even if asked for more, plenary is one group / one table
            "default_table_count": 5,
            "rounds": [{"title": "R1", "question": "What should change?", "duration_minutes": 30}],
        },
    ).json()
    client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/start")
    return assembly


def _join(client, assembly, ip):
    """Every phone scans the SAME shared code."""
    links = client.get(f"/api/v1/assemblies/{assembly['id']}/invites/links").json()
    if not links:
        links = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", links[0]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Origin-IP": ip}
    )
    assert joined.status_code == 200, joined.text
    return joined.json(), {"Authorization": f"Bearer {joined.json()['session_token']}"}


def _start(client, headers, round_id):
    return client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": round_id, "mime_type": "audio/webm"},
        headers=headers,
    )


def test_a_plenary_assembly_has_exactly_one_table(client):
    assembly = _plenary(client)
    assert assembly["default_table_count"] == 1


def test_the_whole_room_shares_one_code(client):
    assembly = _plenary(client)
    links = client.get(f"/api/v1/assemblies/{assembly['id']}/invites/links").json()
    if not links:
        links = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    assert len(links) == 1, "plenary is one shared code, not one per table"


def test_many_devices_record_the_same_round_concurrently(client):
    """The one-phone-per-table 409 must NOT fire — concurrent capture is the
    whole point of the mode."""
    assembly = _plenary(client)
    round_id = assembly["rounds"][0]["id"]

    _, headers_a = _join(client, assembly, "203.0.113.1")
    _, headers_b = _join(client, assembly, "203.0.113.2")
    _, headers_c = _join(client, assembly, "203.0.113.3")

    assert _start(client, headers_a, round_id).status_code == 201
    assert _start(client, headers_b, round_id).status_code == 201, "second phone was refused"
    assert _start(client, headers_c, round_id).status_code == 201, "third phone was refused"


def test_a_device_only_sees_the_round_as_recorded_by_itself(client):
    """Device B must still be offered the round after device A starts — the
    phone-side lock is scoped to the session in plenary."""
    assembly = _plenary(client)
    round_id = assembly["rounds"][0]["id"]

    _, headers_a = _join(client, assembly, "203.0.113.4")
    _start(client, headers_a, round_id)

    # B joins after A is already recording
    joined_b, _ = _join(client, assembly, "203.0.113.5")
    round_for_b = next(r for r in joined_b["rounds"] if r["id"] == round_id)
    assert round_for_b["recorded_state"] is None, (
        "B was told the round is already recorded, though only A has it"
    )


def test_orchestrated_and_independent_still_refuse_a_second_device(client):
    """The relaxation is plenary-only — other modes keep one phone per table."""
    assembly = client.post(
        "/api/v1/assemblies",
        json={"name": "TEST Orch", "recording_mode": "orchestrated", "default_table_count": 1,
              "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}]},
    ).json()
    round_id = assembly["rounds"][0]["id"]
    client.post(f"/api/v1/rounds/{round_id}/start")

    _, headers_a = _join(client, assembly, "203.0.113.6")
    _, headers_b = _join(client, assembly, "203.0.113.7")
    assert _start(client, headers_a, round_id).status_code == 201
    assert _start(client, headers_b, round_id).status_code == 409, "orchestrated must stay one-per-table"
