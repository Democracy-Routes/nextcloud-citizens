# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Clearing the audio off the table phones.

Every recording is written to the phone's own storage before it is uploaded,
so at the end of an assembly each phone still holds its table's audio. With
organisation-owned phones that is untidy; when citizens use their own — now a
supported way to run an assembly — people walk home carrying a recording of
the discussion without knowing it.

The server cannot push to a phone, so the request travels on the status poll
each recorder already makes. That means it reaches phones whose recorder is
still open and no others, which the response has to say honestly rather than
reporting success.
"""

import re

from sqlalchemy import select

from citizens.db.models import Assembly, AuditEvent
from citizens.db.session import session_scope


def _assembly(client, name="TEST Purge"):
    return client.post(
        "/api/v1/assemblies",
        json={
            "name": name,
            "default_table_count": 1,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()


def _join(client, assembly):
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Origin-IP": "203.0.113.7"}
    ).json()
    return {"Authorization": f"Bearer {joined['session_token']}"}, joined


def test_the_purge_is_refused_while_the_session_is_open(client):
    """Until the session closes, each phone's local copy is the backup that
    protects against a failed upload."""
    assembly = _assembly(client)

    response = client.post(f"/api/v1/assemblies/{assembly['id']}/purge-device-audio")

    assert response.status_code == 409
    assert "Close the session first" in response.json()["detail"]


def test_a_closed_session_can_ask_the_phones_to_clear(client):
    assembly = _assembly(client)
    client.post(f"/api/v1/assemblies/{assembly['id']}/close")

    response = client.post(f"/api/v1/assemblies/{assembly['id']}/purge-device-audio")

    assert response.status_code == 200, response.text
    assert response.json()["requested_at"]


def test_the_request_reaches_a_phone_on_its_next_status_poll(client):
    """The whole mechanism: the server cannot push, so it rides on a poll the
    recorder already makes every few seconds."""
    assembly = _assembly(client)
    headers, joined = _join(client, assembly)
    assert joined["purge_local_audio"] is False

    client.post(f"/api/v1/assemblies/{assembly['id']}/close")
    client.post(f"/api/v1/assemblies/{assembly['id']}/purge-device-audio")

    status = client.get("/api/v1/public/recorder/status", headers=headers).json()
    assert status["purge_local_audio"] is True


def test_asking_twice_keeps_the_original_request(client):
    """A second press must not look like a new event to phones that already
    acted on the first."""
    assembly = _assembly(client)
    client.post(f"/api/v1/assemblies/{assembly['id']}/close")

    first = client.post(f"/api/v1/assemblies/{assembly['id']}/purge-device-audio").json()
    second = client.post(f"/api/v1/assemblies/{assembly['id']}/purge-device-audio").json()

    assert first["requested_at"] == second["requested_at"]


def test_the_request_is_audited(client):
    assembly = _assembly(client)
    client.post(f"/api/v1/assemblies/{assembly['id']}/close")
    client.post(f"/api/v1/assemblies/{assembly['id']}/purge-device-audio")

    with session_scope() as session:
        events = session.execute(
            select(AuditEvent).where(AuditEvent.event == "device_audio_purge_requested")
        ).scalars().all()
    assert len(events) == 1


def test_coverage_counts_a_phone_that_has_not_reported_as_unknown(client):
    """Silence is not evidence of an empty phone — it usually means the tab is
    closed. Reporting it as cleared would be a lie the organizer acts on."""
    assembly = _assembly(client)
    _join(client, assembly)
    client.post(f"/api/v1/assemblies/{assembly['id']}/close")

    result = client.post(f"/api/v1/assemblies/{assembly['id']}/purge-device-audio").json()

    assert result["devices"] == 1
    assert result["unknown"] == 1
    assert result["cleared"] == 0


def test_a_phone_reporting_an_empty_store_counts_as_cleared(client):
    assembly = _assembly(client)
    headers, _ = _join(client, assembly)
    client.post(
        "/api/v1/public/recorder/heartbeat",
        json={"recording_active": False, "storage_ok": True, "local_recordings": 0},
        headers=headers,
    )
    client.post(f"/api/v1/assemblies/{assembly['id']}/close")

    result = client.post(f"/api/v1/assemblies/{assembly['id']}/purge-device-audio").json()

    assert result["cleared"] == 1
    assert result["still_holding"] == 0


def test_a_phone_still_holding_audio_is_reported_as_such(client):
    assembly = _assembly(client)
    headers, _ = _join(client, assembly)
    client.post(
        "/api/v1/public/recorder/heartbeat",
        json={"recording_active": False, "storage_ok": True, "local_recordings": 2},
        headers=headers,
    )
    client.post(f"/api/v1/assemblies/{assembly['id']}/close")

    result = client.post(f"/api/v1/assemblies/{assembly['id']}/purge-device-audio").json()

    assert result["still_holding"] == 1
    assert result["cleared"] == 0


def test_an_untouched_assembly_never_asks_its_phones_to_clear(client):
    """The flag must not leak to phones of assemblies nobody purged."""
    assembly = _assembly(client)
    headers, _ = _join(client, assembly)

    status = client.get("/api/v1/public/recorder/status", headers=headers).json()

    assert status["purge_local_audio"] is False
    with session_scope() as session:
        db_assembly = session.get(Assembly, assembly["id"])
        assert db_assembly.device_audio_purge_requested_at is None


# ------------------------------------------ asking automatically when closing


def _closed_assembly(client, auto: bool = True):
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Auto purge",
            "default_table_count": 1,
            "auto_purge_device_audio": auto,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()
    client.post(f"/api/v1/assemblies/{assembly['id']}/close")
    return assembly


def _purge_requested(client, assembly_id) -> bool:
    listing = client.get(f"/api/v1/assemblies/{assembly_id}/files").json()
    return listing["device_audio"]["purge_requested_at"] is not None


def test_closing_asks_the_phones_by_itself(client):
    assembly = _closed_assembly(client)

    assert _purge_requested(client, assembly["id"])


def test_closing_asks_nothing_when_the_organizer_turned_it_off(client):
    assembly = _closed_assembly(client, auto=False)

    assert not _purge_requested(client, assembly["id"])


def test_reopening_withdraws_the_request(client):
    """The flag the phones read is a bare "was this asked for", never
    re-checked against closed_at. Left standing through a reopen, every phone
    joining the reopened assembly is still told to delete — and would clear each
    NEW recording the moment it reached AUDIO_READY, in the middle of a round."""
    assembly = _closed_assembly(client)
    assert _purge_requested(client, assembly["id"])

    client.delete(f"/api/v1/assemblies/{assembly['id']}/close")

    assert not _purge_requested(client, assembly["id"])


def test_a_phone_joining_a_reopened_assembly_is_not_told_to_purge(client):
    """The same thing, seen from where it actually matters."""
    import re

    assembly = _closed_assembly(client)
    client.delete(f"/api/v1/assemblies/{assembly['id']}/close")
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)

    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Origin-IP": "203.0.113.9"}
    )

    assert joined.status_code == 200, joined.text
    assert joined.json()["purge_local_audio"] is False


def test_closing_again_after_a_reopen_asks_again(client):
    assembly = _closed_assembly(client)
    client.delete(f"/api/v1/assemblies/{assembly['id']}/close")

    client.post(f"/api/v1/assemblies/{assembly['id']}/close")

    assert _purge_requested(client, assembly["id"])
