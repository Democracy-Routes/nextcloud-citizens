# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A table whose phone dies must be able to carry on with another one.

Before this, the replacement scanned the same QR code, got a valid session, and
was then refused: the dead phone's recording was still RECORDING, which is not
re-recordable. The only ways out were a twenty-minute sweep and an endpoint no
part of the UI called. On a thirty-minute round that meant losing the rest of
the discussion.

The two ways of releasing the table deliberately differ, because the server
cannot tell a dead battery from dead WiFi — both simply go silent. A dead phone
has stopped recording; a disconnected one is still recording locally and will
upload the backlog when it returns. So the organizer pressing "replace device"
(a person looked at the phone) finalizes the recording, while the automatic
takeover (a timer guessed) leaves it open.
"""

import hashlib
import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from citizens.db.models import AppJob, Recording
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.services.recording import STALLED_DEVICE_SECONDS


def _assembly(client, name="TEST Replacement"):
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": name,
            "default_table_count": 1,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()
    client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/start")
    return assembly


def _join(client, assembly):
    """Scan the table's QR code. Every scan is a new session for that table."""
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Origin-IP": "203.0.113.7"}
    )
    assert joined.status_code == 200, joined.text
    return {"Authorization": f"Bearer {joined.json()['session_token']}"}


def _rejoin(client, assembly):
    """A SECOND phone at the same table, using the same printed code."""
    links = client.get(f"/api/v1/assemblies/{assembly['id']}/invites/links").json()
    token = re.search(r"#/join/(.+)$", links[0]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Origin-IP": "203.0.113.8"}
    )
    assert joined.status_code == 200, joined.text
    return {"Authorization": f"Bearer {joined.json()['session_token']}"}


def _start(client, headers, round_id):
    return client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": round_id, "mime_type": "audio/webm;codecs=opus"},
        headers=headers,
    )


def _upload(client, headers, recording_id, sequence, blob=b"audio-bytes"):
    return client.post(
        f"/api/v1/public/recorder/recordings/{recording_id}/chunks/{sequence}",
        content=blob,
        headers={
            **headers,
            "Content-Type": "application/octet-stream",
            "X-Chunk-SHA256": hashlib.sha256(blob).hexdigest(),
        },
    )


def _age_recording(recording_id, seconds):
    """Make it look like no chunk has arrived for this long."""
    with session_scope() as session:
        recording = session.get(Recording, recording_id)
        recording.updated_at = utcnow() - timedelta(seconds=seconds)


def _state(recording_id):
    with session_scope() as session:
        recording = session.get(Recording, recording_id)
        return recording.state, recording.error_code


@pytest.fixture
def table_recording(client):
    """One table, mid-round, with some audio already uploaded."""
    assembly = _assembly(client)
    round_id = assembly["rounds"][0]["id"]
    headers = _join(client, assembly)
    recording_id = _start(client, headers, round_id).json()["recording_id"]
    assert _upload(client, headers, recording_id, 0).status_code == 200
    return {
        "assembly": assembly,
        "round_id": round_id,
        "headers": headers,
        "recording_id": recording_id,
    }


# ------------------------------------------------ the guard still does its job


def test_a_second_phone_is_refused_while_the_first_is_alive(client, table_recording):
    """The original protection — no accidental extra recordings — must survive."""
    second = _rejoin(client, table_recording["assembly"])

    response = _start(client, second, table_recording["round_id"])

    assert response.status_code == 409
    assert "already recorded" in response.json()["detail"]


# --------------------------------------------- the organizer says it is dead


def test_replacing_the_device_lets_the_next_phone_record(client, table_recording):
    replaced = client.post(
        f"/api/v1/recordings/{table_recording['recording_id']}/replace-device"
    )
    assert replaced.status_code == 200, replaced.text

    second = _rejoin(client, table_recording["assembly"])
    started = _start(client, second, table_recording["round_id"])

    assert started.status_code == 201, started.text
    assert started.json()["recording_id"] != table_recording["recording_id"]


def test_replacing_the_device_finalizes_what_the_dead_phone_sent(client, table_recording):
    """Most of the round is already on the server. It must become a transcript
    without anyone remembering to press Retry afterwards."""
    response = client.post(
        f"/api/v1/recordings/{table_recording['recording_id']}/replace-device"
    )

    assert response.json()["assembling"] is True
    with session_scope() as session:
        jobs = session.execute(
            select(AppJob).where(AppJob.type == "ASSEMBLE_AUDIO")
        ).scalars().all()
    assert len(jobs) == 1
    assert table_recording["recording_id"] in jobs[0].payload_json


def test_replacing_a_device_that_sent_nothing_assembles_nothing(client):
    """No audio arrived, so there is nothing to finalize — but the table must
    still be released, and the round must stop waiting for it."""
    assembly = _assembly(client, "TEST Replacement Empty")
    round_id = assembly["rounds"][0]["id"]
    headers = _join(client, assembly)
    recording_id = _start(client, headers, round_id).json()["recording_id"]

    response = client.post(f"/api/v1/recordings/{recording_id}/replace-device")

    assert response.json()["assembling"] is False
    assert _state(recording_id) == ("UPLOAD_INCOMPLETE", "DEVICE_REPLACED")


def test_replacing_a_device_is_audited(client, table_recording):
    from citizens.db.models import AuditEvent

    client.post(f"/api/v1/recordings/{table_recording['recording_id']}/replace-device")

    with session_scope() as session:
        events = session.execute(
            select(AuditEvent).where(AuditEvent.event == "device_replaced")
        ).scalars().all()
    assert len(events) == 1, "replacing a device left no audit trail"


def test_a_healthy_recording_cannot_be_replaced(client):
    """The endpoint is for stalled recordings, not a way to discard good ones."""
    assembly = _assembly(client, "TEST Replacement Healthy")
    headers = _join(client, assembly)
    recording_id = _start(client, headers, assembly["rounds"][0]["id"]).json()["recording_id"]
    with session_scope() as session:
        session.get(Recording, recording_id).state = "REVIEWED"

    assert client.post(f"/api/v1/recordings/{recording_id}/replace-device").status_code == 409


# ------------------------------------------------------- a timer guesses


def test_a_silent_device_is_taken_over_automatically(client, table_recording):
    """The facilitator may be across the room. The table should not have to
    wait for them."""
    _age_recording(table_recording["recording_id"], STALLED_DEVICE_SECONDS + 30)

    second = _rejoin(client, table_recording["assembly"])
    started = _start(client, second, table_recording["round_id"])

    assert started.status_code == 201, started.text
    assert _state(table_recording["recording_id"]) == ("UPLOAD_INCOMPLETE", "DEVICE_SILENT")


def test_a_briefly_quiet_device_keeps_its_table(client, table_recording):
    """A gap shorter than the threshold is a hiccup, not a dead phone."""
    _age_recording(table_recording["recording_id"], STALLED_DEVICE_SECONDS - 30)

    second = _rejoin(client, table_recording["assembly"])

    assert _start(client, second, table_recording["round_id"]).status_code == 409


def test_the_automatic_takeover_does_not_finalize_the_recording(client, table_recording):
    """The crux of the split. A timer cannot tell a dead battery from dead
    WiFi, and a merely disconnected phone is still recording — so its recording
    must stay open for the backlog it will bring back."""
    _age_recording(table_recording["recording_id"], STALLED_DEVICE_SECONDS + 30)
    second = _rejoin(client, table_recording["assembly"])
    _start(client, second, table_recording["round_id"])

    with session_scope() as session:
        jobs = session.execute(
            select(AppJob).where(AppJob.type == "ASSEMBLE_AUDIO")
        ).scalars().all()
    assert jobs == [], (
        "the automatic takeover assembled the recording, so a phone that was "
        "only offline can no longer upload what it recorded while disconnected"
    )


def test_a_phone_that_was_only_offline_can_still_upload_its_backlog(client, table_recording):
    """The whole reason the two paths differ."""
    _age_recording(table_recording["recording_id"], STALLED_DEVICE_SECONDS + 30)
    second = _rejoin(client, table_recording["assembly"])
    _start(client, second, table_recording["round_id"])

    # phone A's network comes back and it sends what it buffered
    late = _upload(client, table_recording["headers"], table_recording["recording_id"], 1)

    assert late.status_code == 200, late.text
    assert _state(table_recording["recording_id"])[0] == "WAITING_FOR_CHUNKS"


def test_both_recordings_belong_to_the_same_table(client, table_recording):
    """Not a new table: findings count distinct tables, so splitting one group
    in two would count a proposal they discussed either side of the failure as
    two tables raising it independently."""
    client.post(f"/api/v1/recordings/{table_recording['recording_id']}/replace-device")
    second = _rejoin(client, table_recording["assembly"])
    new_id = _start(client, second, table_recording["round_id"]).json()["recording_id"]

    with session_scope() as session:
        first = session.get(Recording, table_recording["recording_id"])
        replacement = session.get(Recording, new_id)
        assert replacement.table_id == first.table_id
        assert replacement.table_number == first.table_number
