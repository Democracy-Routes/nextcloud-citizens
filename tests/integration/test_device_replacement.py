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


# ------------------------------- whose recording is it, from the phone's view


def _status_round(client, headers, round_id):
    """What one phone's status poll says about a round."""
    response = client.get("/api/v1/public/recorder/status", headers=headers)
    assert response.status_code == 200, response.text
    return next(r for r in response.json()["rounds"] if r["id"] == round_id)


def test_a_phone_is_told_the_open_recording_is_its_own(client, table_recording):
    """The recording states in the payload are scoped to the TABLE, not the
    session. Without an ownership flag a phone could not tell its own recording
    from the one a device it replaced left behind — so the armed screen told
    phones, about themselves, that another phone had the table."""
    own = _status_round(
        client, table_recording["headers"], table_recording["round_id"]
    )

    assert own["recorded_state"] == "RECORDING"
    assert own["recorded_by_this_device"] is True


def test_a_second_phone_is_told_the_recording_is_not_its_own(client, table_recording):
    second = _rejoin(client, table_recording["assembly"])

    theirs = _status_round(client, second, table_recording["round_id"])

    assert theirs["recorded_state"] == "RECORDING"
    assert theirs["recorded_by_this_device"] is False


def test_a_replacement_phone_owns_the_round_once_it_records(client, table_recording):
    """After the handover the flag has to follow the table, or the replacement
    phone spends the rest of the round being told it is an impostor."""
    client.post(f"/api/v1/recordings/{table_recording['recording_id']}/replace-device")
    second = _rejoin(client, table_recording["assembly"])
    assert _start(client, second, table_recording["round_id"]).status_code == 201

    theirs = _status_round(client, second, table_recording["round_id"])

    assert theirs["recorded_by_this_device"] is True


def test_an_unrecorded_round_is_owned_by_nobody(client, table_recording):
    assembly = _assembly(client, name="TEST Ownership idle")
    headers = _join(client, assembly)

    idle = _status_round(client, headers, assembly["rounds"][0]["id"])

    assert idle["recorded_state"] is None
    assert idle["recorded_by_this_device"] is False


# ------------------------------- a phone reclaiming its own interrupted round


def test_a_phone_can_restart_its_own_round_without_waiting(client, table_recording):
    """A table that reloaded mid-round was told, by itself, that it had already
    recorded — and nothing released it for two minutes. In orchestrated mode the
    round could be over by then, so a dropped connection cost the table the rest
    of the discussion. The wait exists to stop a DIFFERENT phone taking a live
    table; it has nothing to say about one reclaiming its own work."""
    same_phone = table_recording["headers"]

    response = _start(client, same_phone, table_recording["round_id"])

    assert response.status_code == 201, response.text
    assert response.json()["recording_id"] != table_recording["recording_id"]


def test_reclaiming_keeps_the_audio_already_uploaded(client, table_recording):
    state, error = _state(table_recording["recording_id"])
    assert state == "RECORDING"

    _start(client, table_recording["headers"], table_recording["round_id"])

    # salvaged the same way a replaced device is: the phone that owns this
    # recording is right here starting a new one, so its backlog is never
    # coming — the uploaded half is assembled now, not left to retention. The
    # release stamps DEVICE_REJOINED, then salvage moves it into ASSEMBLING.
    state, error = _state(table_recording["recording_id"])
    assert state in ("ASSEMBLING", "AUDIO_READY", "TRANSCRIBING", "TRANSCRIBED",
                     "ANALYZING", "READY_FOR_REVIEW")


def test_another_phone_still_waits_its_two_minutes(client, table_recording):
    """The guard this relaxes must still hold for a different device."""
    second = _rejoin(client, table_recording["assembly"])

    response = _start(client, second, table_recording["round_id"])

    assert response.status_code == 409
    assert "already recorded" in response.json()["detail"]


def test_a_phone_cannot_re_record_a_round_it_finished(client, table_recording):
    """The reclaim is scoped to a recording still in progress. Once the audio is
    assembled the table HAS recorded the round, and starting again would throw
    finished work away to record over it."""
    headers = table_recording["headers"]
    recording_id = table_recording["recording_id"]
    client.post(
        f"/api/v1/public/recorder/recordings/{recording_id}/complete",
        json={"total_chunks": 1},
        headers=headers,
    )
    with session_scope() as session:
        recording = session.get(Recording, recording_id)
        recording.state = "AUDIO_READY"

    response = _start(client, headers, table_recording["round_id"])

    assert response.status_code == 409
    assert "already recorded" in response.json()["detail"]


# --------------------------------------- salvaging a gap-truncated recording


def _complete(client, headers, recording_id, total):
    return client.post(
        f"/api/v1/public/recorder/recordings/{recording_id}/complete",
        json={"total_chunks": total}, headers=headers,
    )


def test_replace_device_salvages_the_chunks_before_a_gap(client):
    """A phone that uploaded 0,1,2, skipped 3, then sent /complete(total=5)
    lands in WAITING_FOR_CHUNKS — reached ONLY because chunks are missing. The
    old code claimed to assemble it and the job bounced straight back; the real
    audio (the contiguous prefix) could never become a transcript."""
    assembly = _assembly(client, name="TEST Salvage gap")
    round_id = assembly["rounds"][0]["id"]
    headers = _join(client, assembly)
    recording_id = _start(client, headers, round_id).json()["recording_id"]
    for seq in (0, 1, 2, 4):  # 3 missing
        assert _upload(client, headers, recording_id, seq).status_code == 200
    assert _complete(client, headers, recording_id, 5).json()["missing_sequences"] == [3]
    assert _state(recording_id)[0] == "WAITING_FOR_CHUNKS"

    response = client.post(f"/api/v1/recordings/{recording_id}/replace-device")

    assert response.status_code == 200, response.text
    # the contiguous prefix 0,1,2 is salvaged; the gap at 3 truncates the rest.
    # The old code claimed to assemble and the job bounced straight back with
    # nothing usable — now total_chunks is rewritten so assembly can proceed.
    assert response.json()["salvaged_chunks"] == 3
    assert response.json()["assembling"] is True
    with session_scope() as session:
        recording = session.get(Recording, recording_id)
        assert recording.total_chunks == 3
        assert recording.state == "ASSEMBLING"
        jobs = session.execute(
            select(AppJob).where(
                AppJob.type == "ASSEMBLE_AUDIO",
                AppJob.payload_json.contains(recording_id),
            )
        ).scalars().all()
    assert jobs, "the salvaged prefix must be queued for assembly"


def test_a_rejoining_phone_salvages_what_it_already_sent(client):
    """The reclaim path enqueues assembly too: this phone is starting a NEW
    recording, so its backlog is never coming and the uploaded half must be
    assembled now rather than stranded until retention deletes it."""
    assembly = _assembly(client, name="TEST Rejoin salvage")
    round_id = assembly["rounds"][0]["id"]
    headers = _join(client, assembly)
    first = _start(client, headers, round_id).json()["recording_id"]
    for seq in (0, 1, 2):
        assert _upload(client, headers, first, seq).status_code == 200

    # same session reloads and starts again — reclaims its own RECORDING row
    second = _start(client, headers, round_id)
    assert second.status_code == 201

    # the release stamps DEVICE_REJOINED, then salvage assembles the prefix —
    # this phone will never come back to /complete the old id, so the uploaded
    # half must be assembled now rather than stranded until retention
    with session_scope() as session:
        recording = session.get(Recording, first)
        assert recording.error_code == "DEVICE_REJOINED"
        assert recording.state == "ASSEMBLING"
        assert recording.total_chunks == 3
        jobs = session.execute(
            select(AppJob).where(
                AppJob.type == "ASSEMBLE_AUDIO",
                AppJob.payload_json.contains(first),
            )
        ).scalars().all()
    assert jobs, "the rejoining phone's uploaded half must be queued for assembly"
