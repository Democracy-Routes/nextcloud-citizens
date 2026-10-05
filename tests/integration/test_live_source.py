# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One live-caption source per table, however many phones record it.

Every recorder uploads and every recording is transcribed afterwards; only one
feeds the caption engine. The first to start takes it, a backup's chunks are
never fed, any recorder still recording can be promoted, two promotions at once
leave exactly one primary, and the source passes on when its holder stops.
"""

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import select

from citizens.db.models import Recording
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.services.live_captions import LIVE_CAPTIONS
from citizens.services.recording import STALLED_DEVICE_SECONDS


@pytest.fixture
def captions(monkeypatch):
    """Stand in for the caption engine: remember which recordings were fed and
    which sessions were ended, instead of opening provider websockets."""
    fed: list[str] = []
    finished: list[str] = []
    monkeypatch.setattr(LIVE_CAPTIONS, "feed", lambda recording_id, *a, **k: fed.append(recording_id))
    monkeypatch.setattr(LIVE_CAPTIONS, "finish", lambda recording_id: finished.append(recording_id))
    return {"fed": fed, "finished": finished}


def _assembly(client, mode="orchestrated"):
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST live source", "default_table_count": 1, "recording_mode": mode,
            "rounds": [{"title": "R1", "question": "Q", "duration_minutes": 30}],
        },
    ).json()
    client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/start")
    return assembly


def _join(client, url, ip):
    token = re.search(r"#/join/(.+)$", url).group(1)
    body = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Forwarded-For": ip}
    ).json()
    return body, {"Authorization": f"Bearer {body['session_token']}"}


def _second_recorder(client, headers_a, ip):
    card = client.post(
        "/api/v1/public/recorder/capabilities",
        json={"purpose": "ADD_RECORDER_TO_TABLE"}, headers=headers_a,
    ).json()
    return _join(client, card["url"], ip)


def _start(client, headers, round_id):
    response = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": round_id, "mime_type": "audio/webm"}, headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["recording_id"]


def _upload(client, headers, recording_id, sequence, blob=b"audio-bytes"):
    response = client.post(
        f"/api/v1/public/recorder/recordings/{recording_id}/chunks/{sequence}",
        content=blob,
        headers={**headers, "Content-Type": "application/octet-stream",
                 "X-Chunk-SHA256": hashlib.sha256(blob).hexdigest()},
    )
    assert response.status_code == 200, response.text


def _live(client, headers, recording_id):
    return client.get(f"/api/v1/public/recorder/recordings/{recording_id}/live", headers=headers).json()


def _sources(round_id):
    with session_scope() as session:
        return [
            r.id for r in session.execute(
                select(Recording).where(Recording.round_id == round_id, Recording.live_source.is_(True))
            ).scalars()
        ]


def _two_recorders(client):
    assembly = _assembly(client)
    round_id = assembly["rounds"][0]["id"]
    _, phone_a = _join(client, assembly["invites"][0]["url"], "10.8.0.1")
    _, phone_b = _second_recorder(client, phone_a, "10.8.0.2")
    rec_a = _start(client, phone_a, round_id)
    rec_b = _start(client, phone_b, round_id)
    return assembly, round_id, phone_a, phone_b, rec_a, rec_b


def test_a_single_recorder_feeds_captions_as_it_always_did(client, captions):
    assembly = _assembly(client)
    round_id = assembly["rounds"][0]["id"]
    _, phone = _join(client, assembly["invites"][0]["url"], "10.8.0.1")
    recording_id = _start(client, phone, round_id)
    _upload(client, phone, recording_id, 0)
    _upload(client, phone, recording_id, 1)
    assert captions["fed"] == [recording_id, recording_id]
    assert _sources(round_id) == [recording_id]


def test_the_first_recorder_is_the_source_and_the_backup_is_never_fed(client, captions):
    assembly, round_id, phone_a, phone_b, rec_a, rec_b = _two_recorders(client)
    _upload(client, phone_a, rec_a, 0)
    _upload(client, phone_b, rec_b, 0)
    _upload(client, phone_b, rec_b, 1)
    _upload(client, phone_a, rec_a, 1)

    assert captions["fed"] == [rec_a, rec_a]
    assert _sources(round_id) == [rec_a]
    # the backup phone is told whose captions it is watching, not "unavailable"
    assert _live(client, phone_b, rec_b) == {
        "active": False, "lines": [], "reason": "backup",
        "live_source_slot": 1, "live_source_label": "A",
    }
    monitor = client.get(f"/api/v1/rounds/{round_id}/monitor").json()
    [table] = monitor["tables"]
    assert table["live_source_slot"] == 1
    assert [(r["label"], r["recording"]["live_source"]) for r in table["recorders"]] == [
        ("A", True), ("B", False),
    ]


def test_a_backup_can_be_promoted_and_the_old_source_stops_feeding(client, captions):
    assembly, round_id, phone_a, phone_b, rec_a, rec_b = _two_recorders(client)
    promoted = client.post(
        "/api/v1/public/recorder/live-source", json={"recording_id": rec_b}, headers=phone_b
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json() == {"recording_id": rec_b, "live_source": True, "slot": 2}
    # the old holder's caption session was ended; it keeps recording
    assert captions["finished"] == [rec_a]
    _upload(client, phone_a, rec_a, 0)
    _upload(client, phone_b, rec_b, 0)
    assert captions["fed"] == [rec_b]
    assert _sources(round_id) == [rec_b]
    with session_scope() as session:
        assert session.get(Recording, rec_a).state == "RECORDING"
    assert _live(client, phone_a, rec_a)["reason"] == "backup"
    # promoting the holder again changes nothing and ends nothing
    client.post("/api/v1/public/recorder/live-source", json={"recording_id": rec_b}, headers=phone_b)
    assert captions["finished"] == [rec_a]


def test_a_phone_cannot_promote_another_phones_recording(client, captions):
    assembly, round_id, phone_a, phone_b, rec_a, rec_b = _two_recorders(client)
    refused = client.post(
        "/api/v1/public/recorder/live-source", json={"recording_id": rec_a}, headers=phone_b
    )
    assert refused.status_code == 404
    assert _sources(round_id) == [rec_a]


def test_the_organizer_can_promote_and_only_a_recording_in_progress_qualifies(client, captions):
    assembly, round_id, phone_a, phone_b, rec_a, rec_b = _two_recorders(client)
    promoted = client.post(f"/api/v1/recordings/{rec_b}/promote-live-source")
    assert promoted.status_code == 200, promoted.text
    assert _sources(round_id) == [rec_b]
    assert captions["finished"] == [rec_a]

    _upload(client, phone_a, rec_a, 0)
    client.post(f"/api/v1/public/recorder/recordings/{rec_a}/complete",
                json={"total_chunks": 1}, headers=phone_a)
    assert client.post(f"/api/v1/recordings/{rec_a}/promote-live-source").status_code == 409
    other = client.post(f"/api/v1/recordings/{rec_b}/promote-live-source",
                        headers={"X-Test-User": "someone-else"})
    assert other.status_code == 404


def test_two_promotions_at_once_leave_exactly_one_source(client, captions):
    assembly, round_id, phone_a, phone_b, rec_a, rec_b = _two_recorders(client)
    _, phone_c = _second_recorder(client, phone_a, "10.8.0.3")
    rec_c = _start(client, phone_c, round_id)

    def promote(args):
        headers, recording_id = args
        return client.post("/api/v1/public/recorder/live-source",
                           json={"recording_id": recording_id}, headers=headers)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(promote, [(phone_b, rec_b), (phone_c, rec_c)]))
    assert [r.status_code for r in responses] == [200, 200]
    sources = _sources(round_id)
    assert len(sources) == 1 and sources[0] in (rec_b, rec_c)


def test_the_source_passes_on_when_its_holder_stops(client, captions):
    # ...when it completes
    assembly, round_id, phone_a, phone_b, rec_a, rec_b = _two_recorders(client)
    _upload(client, phone_a, rec_a, 0)
    client.post(f"/api/v1/public/recorder/recordings/{rec_a}/complete",
                json={"total_chunks": 1}, headers=phone_a)
    assert _sources(round_id) == [rec_b]
    _upload(client, phone_b, rec_b, 0)
    assert captions["fed"][-1] == rec_b

    # ...and when it goes silent and a replacement takes over its slot
    assembly, round_id, phone_a, phone_b, rec_a, rec_b = _two_recorders(client)
    _upload(client, phone_a, rec_a, 0)
    with session_scope() as session:
        session.get(Recording, rec_a).updated_at = utcnow() - timedelta(seconds=STALLED_DEVICE_SECONDS + 5)
    _, phone_a2 = _join(client, assembly["invites"][0]["url"], "10.8.0.9")
    rec_a2 = _start(client, phone_a2, round_id)
    # B inherited the source the moment A was released; A's replacement is a backup
    assert _sources(round_id) == [rec_b]
    assert _live(client, phone_a2, rec_a2)["reason"] == "backup"
    assert rec_a in captions["finished"]

    # ...and when the organizer replaces the device
    assembly, round_id, phone_a, phone_b, rec_a, rec_b = _two_recorders(client)
    with session_scope() as session:
        session.get(Recording, rec_a).updated_at = utcnow() - timedelta(seconds=STALLED_DEVICE_SECONDS + 5)
    replaced = client.post(f"/api/v1/recordings/{rec_a}/replace-device")
    assert replaced.status_code == 200, replaced.text
    assert _sources(round_id) == [rec_b]


def test_a_table_whose_only_recorder_stops_has_no_source_until_the_next_starts(client, captions):
    assembly = _assembly(client)
    round_id = assembly["rounds"][0]["id"]
    _, phone = _join(client, assembly["invites"][0]["url"], "10.8.0.1")
    recording_id = _start(client, phone, round_id)
    _upload(client, phone, recording_id, 0)
    client.post(f"/api/v1/public/recorder/recordings/{recording_id}/complete",
                json={"total_chunks": 1}, headers=phone)
    assert _sources(round_id) == []
    # "record the rest": the new recording takes the vacant source
    rest = _start(client, phone, round_id)
    assert _sources(round_id) == [rest]


def test_plenary_phones_share_one_live_source_too(client, captions):
    assembly = _assembly(client, mode="plenary")
    round_id = assembly["rounds"][0]["id"]
    _, phone_a = _join(client, assembly["invites"][0]["url"], "10.8.0.1")
    _, phone_b = _join(client, assembly["invites"][0]["url"], "10.8.0.2")
    rec_a = _start(client, phone_a, round_id)
    rec_b = _start(client, phone_b, round_id)
    _upload(client, phone_a, rec_a, 0)
    _upload(client, phone_b, rec_b, 0)
    assert captions["fed"] == [rec_a]
    assert _sources(round_id) == [rec_a]
