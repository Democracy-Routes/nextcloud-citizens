# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Record now follows the language that was spoken (0.7): the engine is asked
to detect it, the first final transcript sets the Session's language once,
later transcripts never flip it back, and a Session whose language was chosen
by hand is never changed."""

import hashlib
import re
import subprocess
import time

from citizens.providers.transcription.base import NormalizedSegment, NormalizedTranscript


class MemoryStore:
    def __init__(self, values=None):
        self.values = values or {}

    def get_value(self, key):
        return self.values.get(key)

    def set_value(self, key, value, sensitive=False):
        self.values[key] = value

    def delete_value(self, key):
        self.values.pop(key, None)


def _transcript(language):
    return NormalizedTranscript(
        provider="deepgram", model="nova-3", language=language,
        segments=[NormalizedSegment(speaker="SPEAKER_01", start=0.2, end=1.1, text="Buongiorno a tutti.")],
        raw={"results": "fake"},
    )


def _record(client, headers, round_id, blob):
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
    return recording_id


def _wait(client, headers, recording_id, timeout=30.0):
    deadline = time.time() + timeout
    state = None
    while time.time() < deadline:
        status = client.get(f"/api/v1/public/recorder/recordings/{recording_id}", headers=headers)
        state = status.json()["state"]
        if state in ("TRANSCRIBED", "ANALYZING", "READY_FOR_REVIEW", "TRANSCRIPTION_FAILED"):
            return state
        time.sleep(0.4)
    return state


def test_record_now_adopts_the_detected_language_once(client, tmp_path, monkeypatch):
    store = MemoryStore({"deepgram_api_key": "dg-test", "stt_provider": "deepgram",
                         "stt_batch_enabled": "1", "analysis_enabled": "0"})
    monkeypatch.setattr("citizens.services.provider_config.default_store", lambda: store)
    seen: list[str] = []
    answers = iter(["it", "en"])

    def fake_transcribe(api_key, path, mime, language, model=""):
        seen.append(language)
        return _transcript(next(answers))

    monkeypatch.setattr(
        "citizens.services.transcription.deepgram_provider.transcribe_file", fake_transcribe
    )
    audio = tmp_path / "s.webm"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "libopus", str(audio)], check=True, timeout=120,
    )
    blob = audio.read_bytes()

    # the organizer's UI said English; the table speaks Italian
    made = client.post("/api/v1/sessions/record-now", json={"language": "en"}).json()
    container = client.get(f"/api/v1/assemblies/{made['container_id']}").json()
    assert container["language"] == "en" and container["language_auto"] is True
    token = re.search(r"#/join/(.+)$", made["recorder_url"]).group(1)
    joined = client.post("/api/v1/public/join", json={"token": token},
                         headers={"X-Forwarded-For": "10.11.0.1"}).json()
    headers = {"Authorization": f"Bearer {joined['session_token']}"}

    first = _record(client, headers, made["session_id"], blob)
    assert _wait(client, headers, first) in ("TRANSCRIBED", "ANALYZING", "READY_FOR_REVIEW")
    assert seen == [""], "no language is forced on an engine that can detect it"
    container = client.get(f"/api/v1/assemblies/{made['container_id']}").json()
    assert container["language"] == "it" and container["language_auto"] is True
    # the phone follows: the status payload carries the room's language
    status = client.get("/api/v1/public/recorder/status", headers=headers).json()
    assert status["assembly"]["language"] == "it"

    # a second table saying "en" does not flip it back
    card = client.post("/api/v1/public/recorder/capabilities",
                       json={"purpose": "ADD_TABLE", "round_id": made["session_id"]}, headers=headers).json()
    card_token = re.search(r"#/join/(.+)$", card["url"]).group(1)
    second = client.post("/api/v1/public/join", json={"token": card_token},
                         headers={"X-Forwarded-For": "10.11.0.2"}).json()
    headers2 = {"Authorization": f"Bearer {second['session_token']}"}
    rec2 = _record(client, headers2, made["session_id"], blob)
    assert _wait(client, headers2, rec2) in ("TRANSCRIBED", "ANALYZING", "READY_FOR_REVIEW")
    assert client.get(f"/api/v1/assemblies/{made['container_id']}").json()["language"] == "it"

    # choosing a language by hand ends the detection
    changed = client.put(f"/api/v1/assemblies/{made['container_id']}", json={"language_auto": False})
    assert changed.status_code == 200 and changed.json()["language_auto"] is False


def test_a_session_with_a_chosen_language_is_never_changed(client, tmp_path, monkeypatch):
    store = MemoryStore({"deepgram_api_key": "dg-test", "stt_provider": "deepgram",
                         "stt_batch_enabled": "1", "analysis_enabled": "0"})
    monkeypatch.setattr("citizens.services.provider_config.default_store", lambda: store)
    seen: list[str] = []

    def fake_transcribe(api_key, path, mime, language, model=""):
        seen.append(language)
        return _transcript("it")

    monkeypatch.setattr(
        "citizens.services.transcription.deepgram_provider.transcribe_file", fake_transcribe
    )
    audio = tmp_path / "s.webm"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "libopus", str(audio)], check=True, timeout=120,
    )
    made = client.post("/api/v1/sessions", json={"question": "Q", "language": "en",
                                                 "recording_mode": "independent"}).json()
    assert client.get(f"/api/v1/assemblies/{made['container_id']}").json()["language_auto"] is False
    token = re.search(r"#/join/(.+)$", made["invites"][0]["url"]).group(1)
    joined = client.post("/api/v1/public/join", json={"token": token},
                         headers={"X-Forwarded-For": "10.11.1.1"}).json()
    headers = {"Authorization": f"Bearer {joined['session_token']}"}
    rec = _record(client, headers, made["session_id"], audio.read_bytes())
    assert _wait(client, headers, rec) in ("TRANSCRIBED", "ANALYZING", "READY_FOR_REVIEW")
    assert seen == ["en"], "the chosen language is forced on the engine"
    assert client.get(f"/api/v1/assemblies/{made['container_id']}").json()["language"] == "en"
