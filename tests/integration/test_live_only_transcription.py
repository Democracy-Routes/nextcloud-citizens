# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Live captions as the transcript of record, and upgrading away from them.

With final transcription switched off, an assembly used to end with nothing at
all: the captions vanished with the session, the recording stopped at
AUDIO_READY, and analysis never ran because it starts from TRANSCRIBED. These
cover the path that replaced that, and the way back out of it.
"""

import hashlib
import json
import re
import subprocess
import time

import pytest

from citizens.config import get_settings
from citizens.providers.transcription.base import NormalizedSegment, NormalizedTranscript
from citizens.storage.paths import live_caption_path


class MemoryStore:
    def __init__(self, values=None):
        self.values = values or {}

    def get_value(self, key):
        return self.values.get(key)

    def set_value(self, key, value, sensitive=False):
        self.values[key] = value

    def delete_value(self, key):
        self.values.pop(key, None)


CAPTIONS = [
    {"t": 0.0, "end": 3.0, "text": "dobbiamo ripulire il fiume", "speaker": 1},
    {"t": 3.2, "end": 6.0, "text": "e servono piu controlli", "speaker": 2},
    {"t": 6.5, "text": "sono d accordo"},
]


@pytest.fixture
def live_only(client, tmp_path, monkeypatch):
    """A recording uploaded with live captions on and final transcription off."""
    store = MemoryStore({
        "stt_provider": "vosk",
        "vosk_url": "ws://vosk.test:2700",
        "stt_live_enabled": "1",
        "stt_batch_enabled": "0",
    })
    monkeypatch.setattr("citizens.services.provider_config.default_store", lambda: store)
    # No real caption engine here: these cover the job that turns a finished
    # session's output into a transcript, so the session itself is stubbed out.
    # Left live, it would connect to nothing and write its own empty file over
    # the fixture's.
    monkeypatch.setattr("citizens.services.live_captions.LIVE_CAPTIONS.feed",
                        lambda *a, **k: None)

    assembly = client.post(
        "/api/v1/assemblies",
        json={"name": "TEST live only", "default_table_count": 1, "language": "it",
              "rounds": [{"title": "R1", "question": "Q", "duration_minutes": 30}]},
    ).json()
    client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/start")
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)
    joined = client.post("/api/v1/public/join", json={"token": token}).json()
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

    def finish(captions=CAPTIONS, final=True):
        """Stand in for the caption session ending and writing what it heard.

        `final` mirrors the real marker the manager writes only on the terminal
        dispose; a normally-finished session is final=True.
        """
        if captions is not None:
            path = live_caption_path(
                get_settings().app_persistent_storage, assembly["id"], recording_id
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "recording_id": recording_id, "provider": "vosk",
                "model": "vosk-model-small-it-0.22", "language": "it",
                "final": final, "lines": captions,
            }))
        client.post(
            f"/api/v1/public/recorder/recordings/{recording_id}/chunks/0",
            content=blob,
            headers={**headers, "Content-Type": "application/octet-stream",
                     "X-Chunk-SHA256": hashlib.sha256(blob).hexdigest()},
        )
        client.post(f"/api/v1/public/recorder/recordings/{recording_id}/complete",
                    json={"total_chunks": 1}, headers=headers)

    return {"client": client, "assembly": assembly, "recording_id": recording_id,
            "headers": headers, "store": store, "finish": finish}


def _wait_state(fixture, targets, timeout=30.0):
    deadline = time.time() + timeout
    status = {}
    while time.time() < deadline:
        status = fixture["client"].get(
            f"/api/v1/public/recorder/recordings/{fixture['recording_id']}",
            headers=fixture["headers"],
        ).json()
        if status["state"] in targets:
            return status
        time.sleep(0.4)
    return status


def test_live_captions_become_the_transcript(live_only):
    live_only["finish"]()
    status = _wait_state(live_only, {"TRANSCRIBED", "ANALYZING", "READY_FOR_REVIEW",
                                     "TRANSCRIPTION_FAILED"})
    assert status["state"] != "TRANSCRIPTION_FAILED", status
    assert status["state"] != "AUDIO_READY", "the pipeline used to stop dead here"

    transcript = live_only["client"].get(
        f"/api/v1/recordings/{live_only['recording_id']}/transcript"
    ).json()
    assert transcript["source"] == "live"
    assert [s["text"] for s in transcript["segments"]] == [c["text"] for c in CAPTIONS]
    # the last caption carried no end time and nothing follows it
    assert transcript["segments"][-1]["end"] > transcript["segments"][-1]["start"]
    assert transcript["segments"][0]["speaker"] == "SPEAKER_01"


def test_the_report_says_where_its_text_came_from(live_only):
    live_only["finish"]()
    _wait_state(live_only, {"TRANSCRIBED", "ANALYZING", "READY_FOR_REVIEW"})

    client, assembly = live_only["client"], live_only["assembly"]
    client.post(f"/api/v1/assemblies/{assembly['id']}/close")
    report = client.get(f"/api/v1/assemblies/{assembly['id']}/report").json()
    assert "live captions" in report["methodology_note"]


def test_captions_that_produced_nothing_are_reported_as_a_failure(live_only):
    """Silence here used to be indistinguishable from a quiet table."""
    live_only["finish"](captions=[])
    status = _wait_state(live_only, {"TRANSCRIPTION_FAILED"})
    assert status["state"] == "TRANSCRIPTION_FAILED"


def test_the_files_tab_marks_a_captions_derived_transcript(live_only):
    live_only["finish"]()
    _wait_state(live_only, {"TRANSCRIBED", "ANALYZING", "READY_FOR_REVIEW"})
    listing = live_only["client"].get(
        f"/api/v1/assemblies/{live_only['assembly']['id']}/files"
    ).json()
    entry = listing["rounds"][0]["tables"][0]
    assert entry["has_transcript"] is True
    assert entry["transcript_source"] == "live"


def test_a_live_transcript_can_be_upgraded_after_analysis(live_only, monkeypatch):
    """The organizer reads the captions, decides they are poor, and asks for a
    real transcription. This used to be refused: the endpoint accepted only
    pre-analysis states, so the only route was the delete-transcript dialog.
    """
    live_only["finish"]()
    _wait_state(live_only, {"TRANSCRIBED", "ANALYZING", "READY_FOR_REVIEW"})
    client, recording_id = live_only["client"], live_only["recording_id"]

    # from here on a real batch transcription is available
    live_only["store"].values["stt_batch_enabled"] = "1"
    monkeypatch.setattr(
        "citizens.services.transcription.vosk_provider.transcribe_file",
        lambda *a, **k: NormalizedTranscript(
            provider="vosk", model="vosk-model-small-it-0.22", language="it",
            segments=[NormalizedSegment(speaker="", start=0.0, end=3.0,
                                        text="il testo vero e proprio")],
            raw={"results": []},
        ),
    )

    response = client.post(f"/api/v1/recordings/{recording_id}/transcribe")
    assert response.status_code == 202, response.text

    deadline = time.time() + 30
    transcript = {}
    while time.time() < deadline:
        transcript = client.get(f"/api/v1/recordings/{recording_id}/transcript").json()
        if transcript.get("source") == "final":
            break
        time.sleep(0.4)
    assert transcript["source"] == "final"
    assert [s["text"] for s in transcript["segments"]] == ["il testo vero e proprio"]

    client.post(f"/api/v1/assemblies/{live_only['assembly']['id']}/close")
    report = client.get(f"/api/v1/assemblies/{live_only['assembly']['id']}/report").json()
    assert "live captions" not in report["methodology_note"]


def test_deleting_the_assembly_takes_the_captions_with_it(live_only):
    """Caption files used to be keyed by recording id alone, outside the
    per-assembly tree that purge_assembly_storage walks — so deleting an
    assembly left the text of what people said on disk, unreachable by anything
    that could delete it later. The device logs made the same mistake once."""
    live_only["finish"]()
    _wait_state(live_only, {"TRANSCRIBED", "ANALYZING", "READY_FOR_REVIEW"})

    path = live_caption_path(
        get_settings().app_persistent_storage,
        live_only["assembly"]["id"],
        live_only["recording_id"],
    )
    assert path.exists(), "the session should have written its captions"

    assert live_only["client"].delete(
        f"/api/v1/assemblies/{live_only['assembly']['id']}"
    ).status_code == 204
    assert not path.exists(), "captions survived the assembly being deleted"


def test_deleting_a_transcript_takes_the_captions_it_came_from(live_only):
    """"Erase the verbatim text of this table" has to mean both copies: the
    transcript rows and the captions they were built from."""
    live_only["finish"]()
    _wait_state(live_only, {"TRANSCRIBED", "ANALYZING", "READY_FOR_REVIEW"})

    path = live_caption_path(
        get_settings().app_persistent_storage,
        live_only["assembly"]["id"],
        live_only["recording_id"],
    )
    assert path.exists()

    response = live_only["client"].delete(
        f"/api/v1/recordings/{live_only['recording_id']}/transcript"
    )
    assert response.status_code == 200, response.text
    assert not path.exists(), "captions survived the transcript being deleted"


def test_a_partial_caption_file_is_not_adopted_until_it_is_final(live_only):
    """A session that died mid-round writes a file that looks complete. The job
    must wait for the terminal 'final' marker rather than promote a prefix —
    otherwise a later append (the successor session's half) is lost."""
    # first write: a non-final partial (the dead session's prefix)
    live_only["finish"](captions=CAPTIONS[:1], final=False)

    # it must NOT become the transcript of record while unfinalized: within the
    # grace window the job retries rather than adopting the partial
    status = _wait_state(live_only, {"TRANSCRIBED", "READY_FOR_REVIEW"}, timeout=6.0)
    assert status["state"] not in ("TRANSCRIBED", "READY_FOR_REVIEW"), (
        "a partial, non-final caption file was adopted as the transcript"
    )

    # the terminal write lands: the full text, marked final
    path = live_caption_path(
        get_settings().app_persistent_storage,
        live_only["assembly"]["id"], live_only["recording_id"],
    )
    path.write_text(json.dumps({
        "recording_id": live_only["recording_id"], "provider": "vosk",
        "model": "vosk-model-small-it-0.22", "language": "it",
        "final": True, "lines": CAPTIONS,
    }))

    status = _wait_state(live_only, {"TRANSCRIBED", "ANALYZING", "READY_FOR_REVIEW"})
    assert status["state"] != "AUDIO_READY", status
    transcript = live_only["client"].get(
        f"/api/v1/recordings/{live_only['recording_id']}/transcript"
    ).json()
    # the full text, not just the partial prefix
    assert [seg["text"] for seg in transcript["segments"]] == [c["text"] for c in CAPTIONS]
