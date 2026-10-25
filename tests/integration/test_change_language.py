# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The organizer changes the language after recording began (0.7, S8): every
recording with audio is transcribed again in it, detection stops, and it is
refused while a session is being recorded."""

import hashlib
import re
import subprocess
import time

from sqlalchemy import select

from citizens.db.models import AppJob, AuditEvent
from citizens.db.session import session_scope
from citizens.providers.transcription.base import NormalizedSegment, NormalizedTranscript
from tests.integration.test_language_detection import MemoryStore


def _transcript(language):
    return NormalizedTranscript(
        provider="deepgram", model="nova-3", language=language,
        segments=[NormalizedSegment(speaker="S1", start=0.2, end=1.1, text="Buongiorno a tutti.")],
        raw={},
    )


def _blob(tmp_path) -> bytes:
    audio = tmp_path / "s.webm"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "libopus", str(audio)], check=True, timeout=120,
    )
    return audio.read_bytes()


def _recorded_assembly(client, tmp_path, monkeypatch, seen, **extra):
    store = MemoryStore({"deepgram_api_key": "dg-test", "stt_provider": "deepgram",
                         "stt_batch_enabled": "1", "analysis_enabled": "0"})
    monkeypatch.setattr("citizens.services.provider_config.default_store", lambda: store)

    def fake_transcribe(api_key, path, mime, language, model=""):
        seen.append(language)
        return _transcript(language or "en")

    monkeypatch.setattr(
        "citizens.services.transcription.deepgram_provider.transcribe_file", fake_transcribe
    )
    assembly = client.post(
        "/api/v1/assemblies",
        json={"name": "TEST Lang", "language": "en", "default_table_count": 1,
              "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}], **extra},
    ).json()
    round_id = assembly["rounds"][0]["id"]
    client.post(f"/api/v1/rounds/{round_id}/start")
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)
    joined = client.post("/api/v1/public/join", json={"token": token},
                         headers={"X-Forwarded-For": "10.12.0.1"}).json()
    headers = {"Authorization": f"Bearer {joined['session_token']}"}
    blob = _blob(tmp_path)
    recording_id = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": round_id, "mime_type": "audio/webm"}, headers=headers,
    ).json()["recording_id"]
    client.post(
        f"/api/v1/public/recorder/recordings/{recording_id}/chunks/0", content=blob,
        headers={**headers, "Content-Type": "application/octet-stream",
                 "X-Chunk-SHA256": hashlib.sha256(blob).hexdigest()},
    )
    client.post(f"/api/v1/public/recorder/recordings/{recording_id}/complete",
                json={"total_chunks": 1}, headers=headers)
    deadline = time.time() + 30
    while time.time() < deadline:
        state = client.get(f"/api/v1/public/recorder/recordings/{recording_id}",
                           headers=headers).json()["state"]
        if state in ("TRANSCRIBED", "READY_FOR_REVIEW", "TRANSCRIPTION_FAILED"):
            break
        time.sleep(0.3)
    assert state == "TRANSCRIBED", state
    return assembly, round_id, recording_id, headers


def test_changing_the_language_transcribes_every_recording_again(client, tmp_path, monkeypatch):
    seen: list[str] = []
    assembly, round_id, recording_id, headers = _recorded_assembly(client, tmp_path, monkeypatch, seen)
    assert seen == ["en"]

    # not while the session is being recorded
    refused = client.post(f"/api/v1/assemblies/{assembly['id']}/language", json={"language": "it"})
    assert refused.status_code == 409 and "SESSION_ACTIVE" in refused.json()["detail"]
    # PUT keeps refusing the field once audio exists — this is the explicit path
    assert client.put(f"/api/v1/assemblies/{assembly['id']}", json={"language": "it"}).status_code == 409

    client.post(f"/api/v1/rounds/{round_id}/end")
    changed = client.post(f"/api/v1/assemblies/{assembly['id']}/language", json={"language": "it"})
    assert changed.status_code == 200, changed.text
    assert changed.json() == {"language": "it", "queued": 1, "skipped_no_audio": 0, "closed": False}
    detail = client.get(f"/api/v1/assemblies/{assembly['id']}").json()
    assert detail["language"] == "it" and detail["language_auto"] is False

    deadline = time.time() + 30
    while time.time() < deadline and seen != ["en", "it"]:
        time.sleep(0.3)
    assert seen == ["en", "it"], "the recording was transcribed again in Italian"
    with session_scope() as session:
        events = session.execute(
            select(AuditEvent.event).where(AuditEvent.event == "language_changed")
        ).scalars().all()
        assert events == ["language_changed"]

    # the same language again queues nothing
    same = client.post(f"/api/v1/assemblies/{assembly['id']}/language", json={"language": "it"})
    assert same.status_code == 200 and same.json()["queued"] == 0
    # an unknown language is refused before anything happens
    unknown = client.post(f"/api/v1/assemblies/{assembly['id']}/language", json={"language": "xx"})
    assert unknown.status_code == 422


def test_refused_while_a_phone_records_even_if_nobody_started_the_round(client, monkeypatch):
    """An independent Session: the phone records without the round ever being
    ACTIVE (seen on the dev instance on 2026-10-13)."""
    made = client.post("/api/v1/sessions/record-now", json={"language": "en"}).json()
    token = re.search(r"#/join/(.+)$", made["recorder_url"]).group(1)
    joined = client.post("/api/v1/public/join", json={"token": token},
                         headers={"X-Forwarded-For": "10.12.0.9"}).json()
    headers = {"Authorization": f"Bearer {joined['session_token']}"}
    started = client.post("/api/v1/public/recorder/start",
                          json={"round_id": made["session_id"], "mime_type": "audio/webm"}, headers=headers)
    assert started.status_code == 201, started.text
    assert client.get(f"/api/v1/sessions/{made['session_id']}").json()["status"] != "ACTIVE"
    refused = client.post(f"/api/v1/assemblies/{made['container_id']}/language", json={"language": "it"})
    assert refused.status_code == 409 and "SESSION_ACTIVE" in refused.json()["detail"]


def test_a_recording_without_audio_is_skipped(client, tmp_path, monkeypatch):
    seen: list[str] = []
    assembly, round_id, recording_id, headers = _recorded_assembly(client, tmp_path, monkeypatch, seen)
    client.post(f"/api/v1/rounds/{round_id}/end")
    deleted = client.delete(f"/api/v1/recordings/{recording_id}/audio")
    assert deleted.status_code in (200, 204), deleted.text
    changed = client.post(f"/api/v1/assemblies/{assembly['id']}/language", json={"language": "fr"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["queued"] == 0 and changed.json()["skipped_no_audio"] == 1
    with session_scope() as session:
        live = session.execute(
            select(AppJob).where(AppJob.type == "TRANSCRIBE_FINAL", AppJob.state.in_(("QUEUED", "RUNNING")))
        ).scalars().all()
        assert live == []
