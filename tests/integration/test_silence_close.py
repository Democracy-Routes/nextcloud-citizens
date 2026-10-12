# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A recording whose phone fell silent is finished by the server, and the
audio the phone sends when it comes back is kept (0.7, R3 / R32).

The phone's uploader stops for good on a 409, so the late chunks must be
accepted under the OLD recording id. They are the next clusters of the same
MediaRecorder stream — decodable only behind the stream's container header,
which the server kept when it closed the recording. Real Opus/WebM, split at
cluster boundaries the way Chrome cuts its chunks, through the real assembly.
"""

import hashlib
import re
import subprocess
import time
from datetime import timedelta

import pytest
from sqlalchemy import select

from citizens.db.models import AuditEvent, Finding, Recording
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.jobs import sweep
from citizens.services import recording as rec_svc
from citizens.services.analysis import _delete_table_findings
from citizens.services.live_audio import WEBM_CLUSTER_ID


def _webm_clusters(tmp_path, seconds: float = 6.0) -> list[bytes]:
    """One WebM, cut where Chrome cuts: chunk 0 = header + first cluster,
    every later chunk = one cluster."""
    path = tmp_path / "stream.webm"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:a", "libopus", "-b:a", "32k", "-cluster_time_limit", "2000", str(path),
        ],
        check=True,
        timeout=120,
    )
    data = path.read_bytes()
    cuts = [m.start() for m in re.finditer(re.escape(WEBM_CLUSTER_ID), data)][1:]
    bounds = [0, *cuts, len(data)]
    chunks = [data[bounds[i]:bounds[i + 1]] for i in range(len(bounds) - 1)]
    assert len(chunks) >= 3, "the stream must have at least three clusters"
    return chunks


@pytest.fixture
def recorder(client):
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Silence",
            "default_table_count": 1,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()
    client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/start")
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Forwarded-For": "10.1.1.9"}
    ).json()
    headers = {"Authorization": f"Bearer {joined['session_token']}"}
    started = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": joined["rounds"][0]["id"], "mime_type": "audio/webm;codecs=opus"},
        headers=headers,
    )
    assert started.status_code == 201, started.text
    return {
        "client": client,
        "assembly": assembly,
        "headers": headers,
        "recording_id": started.json()["recording_id"],
    }


def _upload(recorder, sequence: int, blob: bytes, segment: int = 0):
    return recorder["client"].post(
        f"/api/v1/public/recorder/recordings/{recorder['recording_id']}/chunks/{sequence}",
        content=blob,
        headers={
            **recorder["headers"],
            "Content-Type": "application/octet-stream",
            "X-Chunk-SHA256": hashlib.sha256(blob).hexdigest(),
            "X-Chunk-Segment": str(segment),
        },
    )


def _status(recorder) -> dict:
    return recorder["client"].get(
        f"/api/v1/public/recorder/recordings/{recorder['recording_id']}",
        headers=recorder["headers"],
    ).json()


def _wait_for(recorder, target: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    status = {}
    while time.time() < deadline:
        status = _status(recorder)
        if status["state"] in (target, "AUDIO_INVALID", "UPLOAD_INCOMPLETE"):
            return status
        time.sleep(0.5)
    return status


def _age(recording_id: str, **delta) -> None:
    with session_scope() as session:
        session.get(Recording, recording_id).updated_at = utcnow() - timedelta(**delta)


def _row(recording_id: str) -> Recording:
    with session_scope() as session:
        recording = session.get(Recording, recording_id)
        session.expunge(recording)
        return recording


def _phone_manifest(chunks: list[bytes]) -> tuple[str, int]:
    lines = "".join(
        f"{i}:{len(c)}:{hashlib.sha256(c).hexdigest()}\n" for i, c in enumerate(chunks)
    )
    return hashlib.sha256(lines.encode()).hexdigest(), sum(len(c) for c in chunks)


def test_five_minutes_of_silence_finish_the_recording_with_what_the_server_holds(
    recorder, tmp_path
):
    chunks = _webm_clusters(tmp_path)
    assert _upload(recorder, 0, chunks[0]).status_code == 200
    assert _upload(recorder, 1, chunks[1]).status_code == 200
    _age(recorder["recording_id"], minutes=4)
    assert sweep.sweep_server_closes() == 0  # not yet
    _age(recorder["recording_id"], minutes=6)
    assert sweep.sweep_server_closes() == 1

    row = _row(recorder["recording_id"])
    assert row.closed_by == "silence"
    assert row.total_chunks == 2
    assert row.state in ("ASSEMBLING", "AUDIO_READY")
    status = _wait_for(recorder, "AUDIO_READY")
    assert status["state"] == "AUDIO_READY", status
    with session_scope() as session:
        events = session.execute(
            select(AuditEvent).where(AuditEvent.event == "recording_closed_by_server")
        ).scalars().all()
        assert len(events) == 1


def test_a_silent_recording_with_nothing_uploaded_is_left_alone(recorder):
    _age(recorder["recording_id"], minutes=6)
    assert sweep.sweep_server_closes() == 0
    assert _row(recorder["recording_id"]).state == "RECORDING"


def test_late_chunks_are_kept_and_the_phone_verifies_the_whole_stream(
    recorder, tmp_path, settings_env
):
    chunks = _webm_clusters(tmp_path)
    assert _upload(recorder, 0, chunks[0]).status_code == 200
    assert _upload(recorder, 1, chunks[1]).status_code == 200
    _age(recorder["recording_id"], minutes=6)
    assert sweep.sweep_server_closes() == 1
    assert _wait_for(recorder, "AUDIO_READY")["state"] == "AUDIO_READY"
    # the chunk files are reclaimed; the stream header was kept
    headers = list(settings_env.app_persistent_storage.rglob("late-header-0.bin"))
    assert len(headers) == 1

    # the phone wakes up and carries on where it was, under the old id
    late = _upload(recorder, 2, chunks[2])
    assert late.status_code == 200, late.text
    assert late.json() == {"acknowledged": True, "duplicate": False, "sequence_number": 1}
    original = _row(recorder["recording_id"])
    assert original.continued_by_id and original.audio_added_at is not None
    continuation = _row(original.continued_by_id)
    assert continuation.continued_from_id == original.id
    assert continuation.state == "RECORDING"
    assert continuation.late_header_chunks == 1 and continuation.late_seq_shift == -1
    assert continuation.recorder_session_id == original.recorder_session_id

    # a re-sent late chunk is the same idempotent ACK as always
    assert _upload(recorder, 2, chunks[2]).json()["duplicate"] is True

    # the phone finishes as it always does: its own total, the old id
    done = recorder["client"].post(
        f"/api/v1/public/recorder/recordings/{recorder['recording_id']}/complete",
        json={"total_chunks": 3},
        headers=recorder["headers"],
    )
    assert done.status_code == 200, done.text
    assert done.json()["missing_sequences"] == []
    status = _wait_for(recorder, "AUDIO_READY")
    # ...and what it verifies is the stream it sent: header + mid-stream
    # clusters assembled into real audio on the server
    assert status["state"] == "AUDIO_READY", status
    assert status["continued_by"] == continuation.id
    assert status["total_chunks"] == 3 and status["received_chunks"] == 3
    manifest_sha, manifest_bytes = _phone_manifest(chunks[:3])
    assert status["audio_manifest_sha256"] == manifest_sha
    assert status["audio_manifest_bytes"] == manifest_bytes
    assert status["audio_available"] is True
    assembled = _row(continuation.id)
    assert assembled.state == "AUDIO_READY" and assembled.duration_seconds
    assert 1.0 < assembled.duration_seconds < 4.0  # one two-second cluster, not six seconds
    with session_scope() as session:
        kinds = session.execute(
            select(AuditEvent.event).where(AuditEvent.event == "late_audio_accepted")
        ).scalars().all()
        assert kinds == ["late_audio_accepted"]


def test_a_late_chunk_of_a_new_segment_carries_its_own_header(recorder, tmp_path):
    chunks = _webm_clusters(tmp_path)
    assert _upload(recorder, 0, chunks[0]).status_code == 200
    _age(recorder["recording_id"], minutes=6)
    assert sweep.sweep_server_closes() == 1
    # the watchdog restarted capture: a fresh MediaRecorder session, header first
    late = _upload(recorder, 1, chunks[0], segment=1)
    assert late.status_code == 200, late.text
    assert late.json()["sequence_number"] == 0
    continuation = _row(_row(recorder["recording_id"]).continued_by_id)
    assert continuation.late_header_chunks == 0 and continuation.late_seq_shift == -1


def test_the_organizer_finish_asks_the_phone_then_the_sweep_does_it(recorder, tmp_path):
    chunks = _webm_clusters(tmp_path)
    assert _upload(recorder, 0, chunks[0]).status_code == 200
    client = recorder["client"]
    asked = client.post(f"/api/v1/recordings/{recorder['recording_id']}/finish")
    assert asked.status_code == 200, asked.text
    assert asked.json()["finish_requested_at"]
    # idempotent
    assert client.post(f"/api/v1/recordings/{recorder['recording_id']}/finish").status_code == 200
    # the phone learns on its poll
    poll = client.get("/api/v1/public/recorder/status", headers=recorder["headers"]).json()
    notice = poll["recording_notice"]
    assert notice["recording_id"] == recorder["recording_id"]
    assert notice["finish_requested"] is True and notice["closed_by"] is None
    # a phone that never answers: the sweep finishes for it
    assert sweep.sweep_server_closes() == 0
    with session_scope() as session:
        session.get(Recording, recorder["recording_id"]).finish_requested_at = (
            utcnow() - timedelta(seconds=rec_svc.FINISH_REQUEST_GRACE_SECONDS + 5)
        )
    assert sweep.sweep_server_closes() == 1
    assert _row(recorder["recording_id"]).closed_by == "organizer"
    poll = client.get("/api/v1/public/recorder/status", headers=recorder["headers"]).json()
    assert poll["recording_notice"]["closed_by"] == "organizer"
    # a finished recording cannot be asked again
    assert client.post(f"/api/v1/recordings/{recorder['recording_id']}/finish").status_code == 409


def test_a_late_audio_rerun_keeps_what_the_organizer_approved(recorder):
    recording_id = recorder["recording_id"]
    with session_scope() as session:
        recording = session.get(Recording, recording_id)
        for title, status in (("kept", "APPROVED"), ("edited", "EDITED_AND_APPROVED"),
                              ("draft", "DRAFT"), ("rejected", "REJECTED")):
            session.add(Finding(
                assembly_id=recording.assembly_id, round_id=recording.round_id,
                table_id=recording.table_id, recording_id=recording.id, scope="table",
                type="theme", title=title, status=status,
            ))
        session.flush()
        _delete_table_findings(session, [recording], keep_approved=True)
        left = sorted(session.execute(
            select(Finding.title).where(Finding.recording_id == recording.id)
        ).scalars())
        assert left == ["edited", "kept"]
        _delete_table_findings(session, [recording])
        assert session.execute(
            select(Finding.id).where(Finding.recording_id == recording.id)
        ).first() is None
