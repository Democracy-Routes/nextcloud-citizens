# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One recording out of several MediaRecorder sessions.

A phone that lost its microphone mid-round (screen off on an iPhone, a call)
and got it back keeps the same recording going: the sequence continues, the
new session's chunks carry the next segment number, and its first chunk
opens with a fresh container header. Concatenated mid-stream that is not
decodable, so assembly remuxes each segment on its own and joins them. Real
Opus/WebM audio, the real pipeline.
"""

import hashlib
import json
import re
import subprocess
import time

import pytest


def _webm(tmp_path, name: str, seconds: float, frequency: int = 440) -> bytes:
    path = tmp_path / f"{name}.webm"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={seconds}",
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
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Segments",
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
    started = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": joined["rounds"][0]["id"], "mime_type": "audio/webm;codecs=opus"},
        headers={"Authorization": f"Bearer {joined['session_token']}"},
    )
    assert started.status_code == 201, started.text
    return {
        "client": client,
        "assembly": assembly,
        "headers": {"Authorization": f"Bearer {joined['session_token']}"},
        "recording_id": started.json()["recording_id"],
    }


def _upload(recorder, sequence: int, blob: bytes, segment: int | None = None):
    headers = {
        **recorder["headers"],
        "Content-Type": "application/octet-stream",
        "X-Chunk-SHA256": hashlib.sha256(blob).hexdigest(),
    }
    if segment is not None:
        headers["X-Chunk-Segment"] = str(segment)
    return recorder["client"].post(
        f"/api/v1/public/recorder/recordings/{recorder['recording_id']}/chunks/{sequence}",
        content=blob,
        headers=headers,
    )


def _complete(recorder, total: int):
    return recorder["client"].post(
        f"/api/v1/public/recorder/recordings/{recorder['recording_id']}/complete",
        json={"total_chunks": total},
        headers=recorder["headers"],
    )


def _wait_for_state(recorder, target: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    status = {}
    while time.time() < deadline:
        status = recorder["client"].get(
            f"/api/v1/public/recorder/recordings/{recorder['recording_id']}",
            headers=recorder["headers"],
        ).json()
        if status["state"] in (target, "AUDIO_INVALID"):
            return status
        time.sleep(0.5)
    return status


def _manifest(settings_env) -> dict:
    files = list(settings_env.app_persistent_storage.rglob("manifest.json"))
    assert len(files) == 1, files
    return json.loads(files[0].read_text())


def test_two_sessions_become_one_file(recorder, tmp_path, settings_env):
    """3 s of 440 Hz, the screen goes off, 2 s of 660 Hz: one recording, one
    file, five seconds long."""
    first = _split(_webm(tmp_path, "first", 3.0), 3)
    second = _split(_webm(tmp_path, "second", 2.0, frequency=660), 3)
    for sequence, blob in enumerate(first):
        assert _upload(recorder, sequence, blob, segment=0).status_code == 200
    for offset, blob in enumerate(second):
        assert _upload(recorder, len(first) + offset, blob, segment=1).status_code == 200

    done = _complete(recorder, len(first) + len(second))
    assert done.status_code == 200, done.text
    status = _wait_for_state(recorder, "AUDIO_READY")

    assert status["state"] == "AUDIO_READY", status
    assert status["duration_seconds"] == pytest.approx(5.0, abs=0.6)
    manifest = _manifest(settings_env)
    assert manifest["segments"] == 2
    assert [c["segment"] for c in manifest["chunks"]] == [0, 0, 0, 1, 1, 1]
    assembled = list((settings_env.app_persistent_storage / "assembled").rglob("*.webm"))
    assert len(assembled) == 1


def test_a_late_final_blob_of_the_first_session_still_joins_its_own_bytes(
    recorder, tmp_path, settings_env
):
    """The stopped recorder's last blob can land AFTER the replacement's first
    chunk. It carries segment 0 and belongs at the end of segment 0's stream,
    whatever sequence number it got."""
    first = _split(_webm(tmp_path, "first", 3.0), 3)
    second = _split(_webm(tmp_path, "second", 2.0, frequency=660), 2)
    assert _upload(recorder, 0, first[0], segment=0).status_code == 200
    assert _upload(recorder, 1, first[1], segment=0).status_code == 200
    assert _upload(recorder, 2, second[0], segment=1).status_code == 200
    assert _upload(recorder, 3, first[2], segment=0).status_code == 200  # the straggler
    assert _upload(recorder, 4, second[1], segment=1).status_code == 200

    assert _complete(recorder, 5).status_code == 200
    status = _wait_for_state(recorder, "AUDIO_READY")

    assert status["state"] == "AUDIO_READY", status
    assert status["duration_seconds"] == pytest.approx(5.0, abs=0.6)


def test_no_header_is_the_first_session_and_the_old_path(recorder, tmp_path, settings_env):
    """A recorder build from before 0.6.2 sends no segment: everything is
    segment 0 and assembly is the plain concat-and-remux it always was."""
    chunks = _split(_webm(tmp_path, "only", 3.0), 4)
    for sequence, blob in enumerate(chunks):
        assert _upload(recorder, sequence, blob).status_code == 200

    assert _complete(recorder, len(chunks)).status_code == 200
    status = _wait_for_state(recorder, "AUDIO_READY")

    assert status["state"] == "AUDIO_READY", status
    assert status["duration_seconds"] == pytest.approx(3.0, abs=0.5)
    manifest = _manifest(settings_env)
    assert manifest["segments"] == 1
    assert {c["segment"] for c in manifest["chunks"]} == {0}


def test_the_same_sequence_cannot_change_segment(recorder, tmp_path):
    blob = _split(_webm(tmp_path, "one", 1.0), 1)[0]
    assert _upload(recorder, 0, blob, segment=0).status_code == 200

    again = _upload(recorder, 0, blob, segment=1)

    assert again.status_code == 409
    # the identical chunk, same segment, is still the idempotent ACK
    assert _upload(recorder, 0, blob, segment=0).json()["duplicate"] is True


@pytest.mark.parametrize("segment", ["-1", "1001", "abc"])
def test_a_garbage_segment_is_refused_before_anything_is_stored(recorder, tmp_path, segment):
    blob = _split(_webm(tmp_path, "one", 1.0), 1)[0]
    response = recorder["client"].post(
        f"/api/v1/public/recorder/recordings/{recorder['recording_id']}/chunks/0",
        content=blob,
        headers={
            **recorder["headers"],
            "Content-Type": "application/octet-stream",
            "X-Chunk-SHA256": hashlib.sha256(blob).hexdigest(),
            "X-Chunk-Segment": segment,
        },
    )
    assert response.status_code == 422, response.text
