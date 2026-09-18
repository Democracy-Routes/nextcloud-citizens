# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Batch transcription pipeline: auto-enqueue after assembly, storage, retry API."""

import hashlib
import re
import subprocess
import time

import pytest

from citizens.providers.transcription.base import (
    NormalizedSegment,
    NormalizedTranscript,
    TranscriptionError,
)


class MemoryStore:
    def __init__(self, values=None):
        self.values = values or {}

    def get_value(self, key):
        return self.values.get(key)

    def set_value(self, key, value, sensitive=False):
        self.values[key] = value

    def delete_value(self, key):
        self.values.pop(key, None)


FAKE_TRANSCRIPT = NormalizedTranscript(
    provider="deepgram",
    model="nova-3",
    language="en",
    segments=[
        NormalizedSegment(speaker="SPEAKER_01", start=0.2, end=1.1, text="Hello everyone."),
        NormalizedSegment(speaker="SPEAKER_02", start=1.5, end=2.4, text="Good morning."),
    ],
    raw={"results": "fake"},
)


@pytest.fixture
def recorded(client, tmp_path, monkeypatch):
    """A completed recording that reached AUDIO_READY, with a fake provider
    and an in-memory config store wired in."""
    store = MemoryStore({"deepgram_api_key": "dg-test", "stt_provider": "deepgram",
                         "stt_batch_enabled": "1"})
    monkeypatch.setattr("citizens.services.provider_config.default_store", lambda: store)
    calls = {"transcribe": 0}

    def fake_transcribe(api_key, path, mime, language, model=""):
        calls["transcribe"] += 1
        assert api_key == "dg-test"
        assert path.exists()
        return FAKE_TRANSCRIPT

    monkeypatch.setattr(
        "citizens.services.transcription.deepgram_provider.transcribe_file", fake_transcribe
    )

    assembly = client.post(
        "/api/v1/assemblies",
        json={"name": "TEST STT", "default_table_count": 1,
              "rounds": [{"title": "R1", "question": "Q", "duration_minutes": 30}]},
    ).json()
    client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/start")
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)
    joined = client.post("/api/v1/public/join", json={"token": token},
                         headers={"X-Forwarded-For": "10.3.3.3"}).json()
    headers = {"Authorization": f"Bearer {joined['session_token']}"}

    audio_path = tmp_path / "s.webm"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "libopus", str(audio_path)], check=True, timeout=120,
    )
    blob = audio_path.read_bytes()
    recording_id = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": joined["rounds"][0]["id"], "mime_type": "audio/webm"},
        headers=headers,
    ).json()["recording_id"]
    client.post(
        f"/api/v1/public/recorder/recordings/{recording_id}/chunks/0",
        content=blob,
        headers={**headers, "Content-Type": "application/octet-stream",
                 "X-Chunk-SHA256": hashlib.sha256(blob).hexdigest()},
    )
    client.post(f"/api/v1/public/recorder/recordings/{recording_id}/complete",
                json={"total_chunks": 1}, headers=headers)
    return {"client": client, "recording_id": recording_id, "headers": headers,
            "store": store, "calls": calls}


def _wait_state(fixture, targets, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = fixture["client"].get(
            f"/api/v1/public/recorder/recordings/{fixture['recording_id']}",
            headers=fixture["headers"],
        ).json()
        if status["state"] in targets:
            return status
        time.sleep(0.4)
    return status


def test_auto_transcription_after_assembly(recorded):
    status = _wait_state(recorded, ("TRANSCRIBED",))
    assert status["state"] == "TRANSCRIBED", status
    assert recorded["calls"]["transcribe"] == 1

    transcript = recorded["client"].get(
        f"/api/v1/recordings/{recorded['recording_id']}/transcript"
    ).json()
    assert transcript["provider"] == "deepgram"
    assert len(transcript["segments"]) == 2
    assert transcript["segments"][0]["speaker"] == "SPEAKER_01"
    assert transcript["segments"][1]["text"] == "Good morning."


def test_retranscribe_replaces_transcript(recorded):
    _wait_state(recorded, ("TRANSCRIBED",))
    response = recorded["client"].post(
        f"/api/v1/recordings/{recorded['recording_id']}/transcribe"
    )
    assert response.status_code == 202
    deadline = time.time() + 30
    while recorded["calls"]["transcribe"] < 2 and time.time() < deadline:
        time.sleep(0.4)
    assert recorded["calls"]["transcribe"] == 2
    _wait_state(recorded, ("TRANSCRIBED",))
    transcript = recorded["client"].get(
        f"/api/v1/recordings/{recorded['recording_id']}/transcript"
    ).json()
    assert len(transcript["segments"]) == 2  # replaced, not duplicated


def test_permanent_failure_sets_state(recorded, monkeypatch):
    _wait_state(recorded, ("TRANSCRIBED",))

    def failing(*args, **kwargs):
        raise TranscriptionError("Authentication failed", permanent=True)

    monkeypatch.setattr(
        "citizens.services.transcription.deepgram_provider.transcribe_file", failing
    )
    recorded["client"].post(f"/api/v1/recordings/{recorded['recording_id']}/transcribe")
    status = _wait_state(recorded, ("TRANSCRIPTION_FAILED",))
    assert status["state"] == "TRANSCRIPTION_FAILED"
    # audio stays safe; retry path stays open
    retry = recorded["client"].post(f"/api/v1/recordings/{recorded['recording_id']}/transcribe")
    assert retry.status_code == 202


def test_temporary_failure_is_still_visible_to_the_organizer(recorded, monkeypatch):
    """A retryable failure must persist TRANSCRIPTION_FAILED too.

    The job runner rolls the session back before scheduling a retry, which
    discarded the state set by the handler. Once attempts ran out the job went
    FAILED while the recording sat in TRANSCRIBING forever, showing the
    organizer an "in progress" pill for a recording nothing was working on.
    """
    _wait_state(recorded, ("TRANSCRIBED",))

    def failing(*args, **kwargs):
        raise TranscriptionError("Service unavailable", permanent=False)

    monkeypatch.setattr(
        "citizens.services.transcription.deepgram_provider.transcribe_file", failing
    )
    recorded["client"].post(f"/api/v1/recordings/{recorded['recording_id']}/transcribe")
    status = _wait_state(recorded, ("TRANSCRIPTION_FAILED",))
    assert status["state"] == "TRANSCRIPTION_FAILED", status
    # and the organizer can still act on it
    assert recorded["client"].post(
        f"/api/v1/recordings/{recorded['recording_id']}/transcribe"
    ).status_code == 202


def test_an_unclassified_provider_error_still_shows_as_failed(recorded, monkeypatch):
    """Only TranscriptionError used to be caught. A ValueError from the
    normalizer (a string where a timestamp should be) or from a non-JSON body
    left the job FAILED and the recording TRANSCRIBING forever — an
    in-progress pill for work nothing was doing, and no Re-transcribe button."""
    _wait_state(recorded, ("TRANSCRIBED",))

    def broken(*args, **kwargs):
        raise ValueError("could not convert string to float: '00:12.5'")

    monkeypatch.setattr(
        "citizens.services.transcription.deepgram_provider.transcribe_file", broken
    )
    recorded["client"].post(f"/api/v1/recordings/{recorded['recording_id']}/transcribe")
    status = _wait_state(recorded, ("TRANSCRIPTION_FAILED",))
    assert status["state"] == "TRANSCRIPTION_FAILED", status
    assert recorded["client"].post(
        f"/api/v1/recordings/{recorded['recording_id']}/transcribe"
    ).status_code == 202


def test_a_rate_limited_provider_is_shown_as_rate_limited(recorded, monkeypatch):
    """429 is the one provider failure where pressing Retry is wrong — the job
    is already waiting the provider out. The recording says so."""
    from citizens.db.models import Recording
    from citizens.db.session import session_scope

    _wait_state(recorded, ("TRANSCRIBED",))

    def throttled(*args, **kwargs):
        raise TranscriptionError("Mistral returned HTTP 429 (rate limited): slow down",
                                 status=429, retry_after=5)

    monkeypatch.setattr(
        "citizens.services.transcription.deepgram_provider.transcribe_file", throttled
    )
    recorded["client"].post(f"/api/v1/recordings/{recorded['recording_id']}/transcribe")
    status = _wait_state(recorded, ("TRANSCRIPTION_FAILED",))
    assert status["state"] == "TRANSCRIPTION_FAILED", status
    with session_scope() as session:
        assert session.get(Recording, recorded["recording_id"]).error_code == "RATE_LIMITED"


def test_transcription_jobs_get_enough_attempts_to_wait_out_a_busy_provider(recorded):
    """Hosted STT answered 429 on 4 of 10 tables in the 2026-09-08 load test;
    five attempts span eight minutes, which a provider's busy spell can
    outlast. Both enqueue sites — after assembly and the manual retry —
    give the job an hour."""
    from sqlalchemy import select

    from citizens.db.models import AppJob
    from citizens.db.session import session_scope

    _wait_state(recorded, ("TRANSCRIBED",))
    recorded["client"].post(f"/api/v1/recordings/{recorded['recording_id']}/transcribe")
    with session_scope() as session:
        jobs = [
            job for job in session.scalars(select(AppJob).where(AppJob.type == "TRANSCRIBE_FINAL"))
            if recorded["recording_id"] in job.payload_json
        ]
    assert len(jobs) >= 2, "expected the automatic job and the manual retry"
    assert all(job.max_attempts == 8 for job in jobs), [job.max_attempts for job in jobs]


def test_no_transcription_when_disabled(client, recorded):
    recorded["store"].values["stt_batch_enabled"] = "0"
    # (auto-enqueue check happens at assembly time; covered by unit of readiness)
    from citizens.services import transcription as svc

    assert svc.batch_transcription_ready(recorded["store"]) is False
