# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 2 recorder pipeline: join → record → chunk upload → assemble.

Uses real opus/webm audio generated with ffmpeg and the real assembly
pipeline (concat + ffprobe + remux), exercising duplicate-upload (brief
Test D) and missing-chunk (Test E) behaviour.
"""

import hashlib
import re
import subprocess
import time
from datetime import timedelta

import pytest


def _make_webm_audio(tmp_path, seconds: float = 3.0) -> bytes:
    path = tmp_path / "source.webm"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:a", "libopus", "-b:a", "32k", str(path),
        ],
        check=True,
        timeout=120,
    )
    return path.read_bytes()


def _split(data: bytes, parts: int) -> list[bytes]:
    size = len(data) // parts + 1
    return [data[i * size : (i + 1) * size] for i in range(parts) if data[i * size : (i + 1) * size]]


@pytest.fixture
def recorder(client):
    """An assembly with invites, joined as the table-1 recorder."""
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Recorder",
            "default_table_count": 2,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()
    client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/start")
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Forwarded-For": "10.1.1.1"}
    )
    assert joined.status_code == 200, joined.text
    data = joined.json()
    return {
        "client": client,
        "assembly": assembly,
        "headers": {"Authorization": f"Bearer {data['session_token']}"},
        "round_id": data["rounds"][0]["id"],
    }


def _upload(recorder, recording_id: str, sequence: int, blob: bytes, sha=None):
    return recorder["client"].post(
        f"/api/v1/public/recorder/recordings/{recording_id}/chunks/{sequence}",
        content=blob,
        headers={
            **recorder["headers"],
            "Content-Type": "application/octet-stream",
            "X-Chunk-SHA256": sha or hashlib.sha256(blob).hexdigest(),
        },
    )


def _start(recorder) -> str:
    response = recorder["client"].post(
        "/api/v1/public/recorder/start",
        json={"round_id": recorder["round_id"], "mime_type": "audio/webm;codecs=opus"},
        headers=recorder["headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()["recording_id"]


def _wait_for_state(recorder, recording_id: str, target: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    status = {}
    while time.time() < deadline:
        status = (
            recorder["client"]
            .get(f"/api/v1/public/recorder/recordings/{recording_id}", headers=recorder["headers"])
            .json()
        )
        if status["state"] in (target, "AUDIO_INVALID"):
            return status
        time.sleep(0.5)
    return status


def test_full_recording_pipeline(recorder, tmp_path, settings_env):
    audio = _make_webm_audio(tmp_path)
    chunks = _split(audio, 4)
    recording_id = _start(recorder)

    for sequence, blob in enumerate(chunks):
        response = _upload(recorder, recording_id, sequence, blob)
        assert response.status_code == 200, response.text
        assert response.json() == {
            "acknowledged": True, "duplicate": False, "sequence_number": sequence,
        }

    done = recorder["client"].post(
        f"/api/v1/public/recorder/recordings/{recording_id}/complete",
        json={"total_chunks": len(chunks)},
        headers=recorder["headers"],
    )
    assert done.status_code == 200, done.text
    assert done.json()["state"] == "ASSEMBLING"

    status = _wait_for_state(recorder, recording_id, "AUDIO_READY")
    assert status["state"] == "AUDIO_READY", status
    assert status["duration_seconds"] == pytest.approx(3.0, abs=0.5)

    # canonical file exists and is valid audio
    assembled = list((settings_env.app_persistent_storage / "assembled").rglob("*.webm"))
    assert len(assembled) == 1
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(assembled[0])],
        capture_output=True, text=True, check=True,
    )
    assert float(probe.stdout.strip()) == pytest.approx(3.0, abs=0.5)


def test_duplicate_chunk_is_idempotent(recorder, tmp_path):
    """Brief §56 Test D."""
    audio = _make_webm_audio(tmp_path, seconds=1.0)
    chunks = _split(audio, 2)
    recording_id = _start(recorder)

    assert _upload(recorder, recording_id, 0, chunks[0]).json()["duplicate"] is False
    duplicate = _upload(recorder, recording_id, 0, chunks[0])
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True

    # same sequence with DIFFERENT bytes must be rejected
    conflict = _upload(recorder, recording_id, 0, chunks[1])
    assert conflict.status_code == 409

    status = recorder["client"].get(
        f"/api/v1/public/recorder/recordings/{recording_id}", headers=recorder["headers"]
    ).json()
    assert status["received_chunks"] == 1


def test_missing_chunk_detected_and_recoverable(recorder, tmp_path):
    """Brief §56 Test E: server refuses to assemble with a gap."""
    audio = _make_webm_audio(tmp_path, seconds=2.0)
    chunks = _split(audio, 4)
    recording_id = _start(recorder)

    for sequence in (0, 1, 3):
        assert _upload(recorder, recording_id, sequence, chunks[sequence]).status_code == 200

    done = recorder["client"].post(
        f"/api/v1/public/recorder/recordings/{recording_id}/complete",
        json={"total_chunks": 4},
        headers=recorder["headers"],
    ).json()
    assert done["state"] == "WAITING_FOR_CHUNKS"
    assert done["missing_sequences"] == [2]

    # resend the gap, complete again
    assert _upload(recorder, recording_id, 2, chunks[2]).status_code == 200
    done = recorder["client"].post(
        f"/api/v1/public/recorder/recordings/{recording_id}/complete",
        json={"total_chunks": 4},
        headers=recorder["headers"],
    ).json()
    assert done["state"] == "ASSEMBLING"
    assert _wait_for_state(recorder, recording_id, "AUDIO_READY")["state"] == "AUDIO_READY"


def test_revoking_invites_disconnects_devices_already_joined(recorder):
    """Revoke used to cancel the invite only, leaving anyone who had already
    joined — including someone who photographed the QR poster — a working
    session for up to 16 more hours."""
    assembly_id = recorder["assembly"]["id"]
    assert recorder["client"].get(
        "/api/v1/public/recorder/status", headers=recorder["headers"]
    ).status_code == 200

    assert recorder["client"].post(
        f"/api/v1/assemblies/{assembly_id}/invites/revoke"
    ).status_code == 204

    kicked = recorder["client"].get(
        "/api/v1/public/recorder/status", headers=recorder["headers"]
    )
    assert kicked.status_code == 401


def test_regenerating_qr_sheets_does_not_kick_live_tables(recorder):
    """New codes must not knock tables off mid-round — only an explicit
    Revoke disconnects."""
    assembly_id = recorder["assembly"]["id"]
    recorder["client"].post(f"/api/v1/assemblies/{assembly_id}/invites/generate")
    assert recorder["client"].get(
        "/api/v1/public/recorder/status", headers=recorder["headers"]
    ).status_code == 200


def test_chunks_are_reclaimed_once_the_audio_is_verified(recorder, tmp_path):
    """Chunks are the upload transport, not a second archive. Nothing ever
    collected them, so every recording sat on disk twice, permanently."""
    from sqlalchemy import select

    from citizens.config import get_settings
    from citizens.db.models import AudioChunk, Recording
    from citizens.db.session import session_scope
    from citizens.storage.paths import recording_dir

    audio = _make_webm_audio(tmp_path, seconds=2.0)
    parts = _split(audio, 3)
    recording_id = _start(recorder)
    for sequence, part in enumerate(parts):
        assert _upload(recorder, recording_id, sequence, part).status_code == 200
    recorder["client"].post(
        f"/api/v1/public/recorder/recordings/{recording_id}/complete",
        json={"total_chunks": len(parts)},
        headers=recorder["headers"],
    )
    assert _wait_for_state(recorder, recording_id, "AUDIO_READY")["state"] == "AUDIO_READY"

    root = get_settings().app_persistent_storage

    # Reclamation now happens AFTER the commit that records AUDIO_READY, on
    # purpose: unlinking the files first meant that a failed commit rolled the
    # chunk rows back while their bytes were already gone, and every retry then
    # failed permanently. So the state is visible a moment before the chunks
    # are collected, and this waits for the collection rather than assuming the
    # two are atomic.
    for _ in range(100):
        with session_scope() as session:
            remaining = session.execute(
                select(AudioChunk).where(AudioChunk.recording_id == recording_id)
            ).scalars().all()
        if not remaining:
            break
        time.sleep(0.1)
    assert remaining == [], "the per-chunk copies were never reclaimed"

    with session_scope() as session:
        recording = session.get(Recording, recording_id)
        # the canonical audio and its checksum survive...
        assert recording.sha256
        assert (root / recording.canonical_audio_path).is_file()
        directory = recording_dir(
            root, recording.assembly_id, recording.round_id, recording.table_id, recording.id
        )
    # ...and so does the per-chunk audit trail, without the bytes
    assert (directory / "manifest.json").is_file()
    assert not (directory / "chunks").exists()


def test_dead_phone_no_longer_wedges_the_round(recorder, tmp_path):
    """A phone that dies mid-upload leaves WAITING_FOR_CHUNKS, which counted as
    healthy-pending — so the round's cross-table analysis waited on it forever
    and the table could not re-record either. It is reachable now."""
    from citizens.db.models import Recording
    from citizens.db.models.base import utcnow
    from citizens.db.session import session_scope
    from citizens.jobs.sweep import STALLED_UPLOAD_MINUTES, sweep_stalled_uploads
    from citizens.services.recording import RERECORDABLE_STATES

    audio = _make_webm_audio(tmp_path, seconds=2.0)
    chunks = _split(audio, 4)
    recording_id = _start(recorder)
    for sequence in (0, 1, 3):
        _upload(recorder, recording_id, sequence, chunks[sequence])
    done = recorder["client"].post(
        f"/api/v1/public/recorder/recordings/{recording_id}/complete",
        json={"total_chunks": 4},
        headers=recorder["headers"],
    ).json()
    assert done["state"] == "WAITING_FOR_CHUNKS"

    # nothing is coming; the sweep leaves it alone until it is genuinely stale
    assert sweep_stalled_uploads() == 0
    with session_scope() as session:
        recording = session.get(Recording, recording_id)
        recording.updated_at = utcnow() - timedelta(minutes=STALLED_UPLOAD_MINUTES + 1)

    assert sweep_stalled_uploads() == 1
    with session_scope() as session:
        recording = session.get(Recording, recording_id)
        assert recording.state == "UPLOAD_INCOMPLETE"
        assert recording.error_code == "UPLOAD_TIMED_OUT"
    # and the table can start over, which WAITING_FOR_CHUNKS did not allow
    assert "UPLOAD_INCOMPLETE" in RERECORDABLE_STATES


def test_organizer_can_abandon_a_stalled_upload(recorder, tmp_path):
    """During a live event nobody can wait for the sweep."""
    audio = _make_webm_audio(tmp_path, seconds=2.0)
    chunks = _split(audio, 4)
    recording_id = _start(recorder)
    for sequence in (0, 1, 3):
        _upload(recorder, recording_id, sequence, chunks[sequence])
    recorder["client"].post(
        f"/api/v1/public/recorder/recordings/{recording_id}/complete",
        json={"total_chunks": 4},
        headers=recorder["headers"],
    )
    response = recorder["client"].post(f"/api/v1/recordings/{recording_id}/abandon-upload")
    assert response.status_code == 200
    assert response.json()["state"] == "UPLOAD_INCOMPLETE"
    # not applicable to a healthy recording
    again = recorder["client"].post(f"/api/v1/recordings/{recording_id}/abandon-upload")
    assert again.status_code == 409


def test_checksum_mismatch_rejected(recorder):
    recording_id = _start(recorder)
    response = _upload(recorder, recording_id, 0, b"real-bytes", sha="0" * 64)
    assert response.status_code == 400
    assert "hecksum" in response.json()["detail"]


def test_recorder_auth_rules(recorder):
    client = recorder["client"]
    # no bearer
    assert client.get("/api/v1/public/recorder/status").status_code == 401
    # garbage bearer
    assert (
        client.get(
            "/api/v1/public/recorder/status", headers={"Authorization": "Bearer nonsense"}
        ).status_code
        == 401
    )
    # invalid invite token
    assert (
        client.post(
            "/api/v1/public/join", json={"token": "x" * 43}, headers={"X-Forwarded-For": "10.9.9.9"}
        ).status_code
        == 401
    )


def test_join_rate_limited(client):
    headers = {"X-Forwarded-For": "10.7.7.7"}
    for _ in range(10):
        client.post("/api/v1/public/join", json={"token": "y" * 43}, headers=headers)
    throttled = client.post("/api/v1/public/join", json={"token": "y" * 43}, headers=headers)
    assert throttled.status_code == 429


def test_every_table_can_join_from_one_venue_address(client):
    """At a venue all phones share one NAT'd address. Keying the budget on the
    IP threw 429 at tables 11+ while they were scanning their QR codes; the
    budget belongs to the invite token, one per table."""
    headers = {"X-Origin-IP": "203.0.113.5"}
    statuses = [
        client.post(
            "/api/v1/public/join", json={"token": f"table{n:02d}{'z' * 36}"}, headers=headers
        ).status_code
        for n in range(20)
    ]
    assert 429 not in statuses, statuses
    assert set(statuses) == {401}  # rejected as unknown tokens, never throttled


def test_forwarded_for_cannot_reset_the_flood_budget(client):
    """X-Forwarded-For is client-controlled, so preferring it let anyone mint a
    fresh bucket per request. AppAPI sets x-origin-ip itself and strips any
    incoming copy, so that is what the backstop counts."""
    origin = "198.51.100.9"
    for n in range(120):
        client.post(
            "/api/v1/public/join",
            json={"token": f"flood{n:03d}{'q' * 35}"},
            headers={"X-Origin-IP": origin, "X-Forwarded-For": f"10.0.0.{n % 250}"},
        )
    throttled = client.post(
        "/api/v1/public/join",
        json={"token": f"final{'q' * 38}"},
        headers={"X-Origin-IP": origin, "X-Forwarded-For": "10.0.0.251"},
    )
    assert throttled.status_code == 429


def test_giving_up_on_a_table_is_reversible(recorder, tmp_path):
    """Abandoning a stalled upload must never cost audio: a phone that regains
    signal afterwards has to be able to finish uploading."""
    audio = _make_webm_audio(tmp_path, seconds=2.0)
    parts = _split(audio, 3)
    recording_id = _start(recorder)
    _upload(recorder, recording_id, 0, parts[0])

    # organizer stops waiting mid-recording (phone died, round must move on)
    abandoned = recorder["client"].post(f"/api/v1/recordings/{recording_id}/abandon-upload")
    assert abandoned.status_code == 200
    assert abandoned.json()["state"] == "UPLOAD_INCOMPLETE"

    # the phone comes back and finishes
    assert _upload(recorder, recording_id, 1, parts[1]).status_code == 200
    assert _upload(recorder, recording_id, 2, parts[2]).status_code == 200
    done = recorder["client"].post(
        f"/api/v1/public/recorder/recordings/{recording_id}/complete",
        json={"total_chunks": 3},
        headers=recorder["headers"],
    ).json()
    assert done["state"] == "ASSEMBLING"
    assert _wait_for_state(recorder, recording_id, "AUDIO_READY")["state"] == "AUDIO_READY"
