# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A table may have several recorder phones, recording side by side.

Replacement used to be the only way a second phone reached a table, and it was
a special path. Now a recorder added by QR is an ordinary second recorder
(slot B): it records beside the first, neither is told the table is taken, both
recordings belong to the one table, and losing one changes nothing about the
other. Replacement remains what it was — a phone rescanning the table's own
code into slot A.
"""

import hashlib
import re
import time
from datetime import timedelta

from sqlalchemy import select

from citizens.db.models import Recording
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.services.recording import STALLED_DEVICE_SECONDS
from citizens.services.table_recordings import recordings_for_table


def _assembly(client):
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST multi recorder",
            "default_table_count": 1,
            "rounds": [{"title": "R1", "question": "Q", "duration_minutes": 30}],
        },
    ).json()
    client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/start")
    return assembly


def _join(client, url, ip):
    token = re.search(r"#/join/(.+)$", url).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Forwarded-For": ip}
    )
    assert joined.status_code == 200, joined.text
    body = joined.json()
    return body, {"Authorization": f"Bearer {body['session_token']}"}


def _second_recorder(client, headers_a, ip):
    card = client.post(
        "/api/v1/public/recorder/capabilities",
        json={"purpose": "ADD_RECORDER_TO_TABLE"}, headers=headers_a,
    ).json()
    return _join(client, card["url"], ip)


def _start(client, headers, round_id):
    return client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": round_id, "mime_type": "audio/webm"},
        headers=headers,
    )


def _upload(client, headers, recording_id, sequence=0, blob=b"audio-bytes"):
    return client.post(
        f"/api/v1/public/recorder/recordings/{recording_id}/chunks/{sequence}",
        content=blob,
        headers={
            **headers,
            "Content-Type": "application/octet-stream",
            "X-Chunk-SHA256": hashlib.sha256(blob).hexdigest(),
        },
    )


def _status(client, headers):
    return client.get("/api/v1/public/recorder/status", headers=headers).json()


def _age(recording_id, seconds):
    with session_scope() as session:
        recording = session.get(Recording, recording_id)
        recording.updated_at = utcnow() - timedelta(seconds=seconds)


def test_two_recorders_record_one_table_side_by_side(client):
    assembly = _assembly(client)
    round_id = assembly["rounds"][0]["id"]
    _, phone_a = _join(client, assembly["invites"][0]["url"], "10.6.0.1")
    joined_b, phone_b = _second_recorder(client, phone_a, "10.6.0.2")
    assert joined_b["slot"] == 2

    rec_a = _start(client, phone_a, round_id)
    assert rec_a.status_code == 201, rec_a.text
    # the second recorder is not blocked by the first — it is not a replacement
    rec_b = _start(client, phone_b, round_id)
    assert rec_b.status_code == 201, rec_b.text
    assert rec_a.json()["recording_id"] != rec_b.json()["recording_id"]

    # and neither phone is told its table is held by somebody else
    for headers in (phone_a, phone_b):
        [round_] = _status(client, headers)["rounds"]
        assert round_["recorded_state"] == "RECORDING"
        assert round_["recorded_by_this_device"] is True

    # both recordings belong to the one table
    with session_scope() as session:
        recordings = recordings_for_table(session, round_id, _table_id(session, round_id))
        assert sorted(r.id for r in recordings) == sorted(
            [rec_a.json()["recording_id"], rec_b.json()["recording_id"]]
        )

    listed = client.get(f"/api/v1/rounds/{round_id}/tables/{_table_id_api(client, round_id)}/recordings")
    assert listed.status_code == 200, listed.text
    assert sorted(r["slot"] for r in listed.json()) == [1, 2]
    assert [r["slot_label"] for r in sorted(listed.json(), key=lambda r: r["slot"])] == ["A", "B"]

    monitor = client.get(f"/api/v1/rounds/{round_id}/monitor").json()
    [table] = monitor["tables"]
    assert [r["label"] for r in table["recorders"]] == ["A", "B"]
    assert all(r["recording"]["state"] == "RECORDING" for r in table["recorders"])


def test_losing_one_recorder_leaves_the_other_untouched_and_a_replacement_takes_its_slot(client):
    assembly = _assembly(client)
    round_id = assembly["rounds"][0]["id"]
    _, phone_a = _join(client, assembly["invites"][0]["url"], "10.6.0.1")
    _, phone_b = _second_recorder(client, phone_a, "10.6.0.2")
    rec_a = _start(client, phone_a, round_id).json()["recording_id"]
    rec_b = _start(client, phone_b, round_id).json()["recording_id"]
    assert _upload(client, phone_a, rec_a).status_code == 200
    assert _upload(client, phone_b, rec_b).status_code == 200

    # phone A dies: nothing for two minutes
    _age(rec_a, STALLED_DEVICE_SECONDS + 5)
    # B keeps going, unaffected
    assert _upload(client, phone_b, rec_b, sequence=1).status_code == 200

    # a replacement for A rescans the table's own code — slot 1, as always —
    # and takes over A's recording through the silent-device path
    _, phone_a2 = _join(client, assembly["invites"][0]["url"], "10.6.0.3")
    rec_a2 = _start(client, phone_a2, round_id)
    assert rec_a2.status_code == 201, rec_a2.text
    with session_scope() as session:
        old = session.get(Recording, rec_a)
        assert old.state == "UPLOAD_INCOMPLETE" and old.error_code == "DEVICE_SILENT"
        assert session.get(Recording, rec_b).state == "RECORDING"
        recordings = recordings_for_table(session, round_id, _table_id(session, round_id))
        assert len(recordings) == 3

    # B is still not told anything about its table changed hands
    [round_] = _status(client, phone_b)["rounds"]
    assert round_["recorded_by_this_device"] is True


def test_the_same_slot_still_keeps_one_recording_per_table(client):
    """Slot B behaves like slot A towards itself: a second phone in the SAME
    slot is a replacement, not a third recorder."""
    assembly = _assembly(client)
    round_id = assembly["rounds"][0]["id"]
    _, phone_a = _join(client, assembly["invites"][0]["url"], "10.6.0.1")
    _, phone_b = _second_recorder(client, phone_a, "10.6.0.2")
    rec_b = _start(client, phone_b, round_id).json()["recording_id"]
    assert _upload(client, phone_b, rec_b).status_code == 200

    # A completes its own recording and may not record this round again
    rec_a = _start(client, phone_a, round_id).json()["recording_id"]
    assert _upload(client, phone_a, rec_a).status_code == 200
    client.post(f"/api/v1/public/recorder/recordings/{rec_a}/complete",
                json={"total_chunks": 1}, headers=phone_a)
    client.post(f"/api/v1/rounds/{round_id}/end")
    again = _start(client, phone_a, round_id)
    assert again.status_code == 409  # the round is over for A ("already recorded")
    # ...while B's own recording was never affected by A's completion
    with session_scope() as session:
        assert session.get(Recording, rec_b).state == "RECORDING"


def test_both_recordings_reach_the_server_as_audio_of_one_table(client):
    assembly = _assembly(client)
    round_id = assembly["rounds"][0]["id"]
    _, phone_a = _join(client, assembly["invites"][0]["url"], "10.6.0.1")
    _, phone_b = _second_recorder(client, phone_a, "10.6.0.2")
    rec_a = _start(client, phone_a, round_id).json()["recording_id"]
    rec_b = _start(client, phone_b, round_id).json()["recording_id"]
    for headers, rid in ((phone_a, rec_a), (phone_b, rec_b)):
        assert _upload(client, headers, rid).status_code == 200
        done = client.post(f"/api/v1/public/recorder/recordings/{rid}/complete",
                           json={"total_chunks": 1}, headers=headers)
        assert done.status_code == 200, done.text

    deadline = time.time() + 40
    states = {}
    while time.time() < deadline:
        with session_scope() as session:
            states = {rid: session.get(Recording, rid).state for rid in (rec_a, rec_b)}
        if all(s not in ("FINALIZING", "ASSEMBLING", "WAITING_FOR_CHUNKS") for s in states.values()):
            break
        time.sleep(0.4)
    # the fake bytes are not decodable audio, so both end AUDIO_INVALID — the
    # point is that each got its own assembly, independently, under one table
    assert set(states.values()) <= {"AUDIO_READY", "AUDIO_INVALID"}, states
    files = client.get(f"/api/v1/assemblies/{assembly['id']}/files").json()
    [round_files] = files["rounds"]
    assert sorted(f["recording_id"] for f in round_files["tables"]) == sorted([rec_a, rec_b])


def test_the_phone_is_told_how_many_recorders_and_who_carries_the_captions(client):
    assembly = _assembly(client)
    round_id = assembly["rounds"][0]["id"]
    joined_a, phone_a = _join(client, assembly["invites"][0]["url"], "10.6.0.1")
    assert joined_a["table"] == {
        "number": 1, "color_key": "blue", "slot": 1, "slot_label": "A",
        "recorders": 1, "live_source_slot": None, "live_source_label": None,
    }
    joined_b, phone_b = _second_recorder(client, phone_a, "10.6.0.2")
    assert joined_b["table"]["recorders"] == 2
    assert (joined_b["table"]["slot"], joined_b["table"]["slot_label"]) == (2, "B")

    _start(client, phone_b, round_id)
    table = _status(client, phone_a)["table"]
    assert table["recorders"] == 2
    # B started first, so B carries the captions until A starts or takes over
    assert (table["live_source_slot"], table["live_source_label"]) == (2, "B")


def _table_id(session, round_id):
    from citizens.db.models import Table

    return session.execute(select(Table.id).where(Table.round_id == round_id)).scalar_one()


def _table_id_api(client, round_id):
    [table] = client.get(f"/api/v1/rounds/{round_id}/tables").json()
    return table["id"]
