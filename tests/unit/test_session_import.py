# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Session import and attached files, the pure parts: what a transcript from
outside must look like, how an upload is received in parts, and which
recording states may take attached material."""

import hashlib
import time

import pytest

from citizens.services import session_import, uploads
from citizens.services.recording_states import ALLOWED_TRANSITIONS


def test_transcript_shape_of_an_export_is_taken_as_is():
    data = {
        "provider": "mistral", "model": "voxtral-small-transcribe-3", "language": "it",
        "segments": [
            {"id": "x", "speaker": "SPEAKER_01", "start": 0.8, "end": 2.1, "text": "  Buongiorno a  tutti "},
            {"speaker": "", "start": 2.5, "end": 3.0, "text": ""},
            {"speaker_label": "SPEAKER_02", "start": 3, "end": 4, "text": "Sì",
             "words": [{"text": "Sì", "start": 3.0, "end": 3.4}]},
        ],
        "raw": {"anything": True},
    }
    normalized = session_import.parse_transcript(data)
    assert (normalized.provider, normalized.model, normalized.language) == (
        "mistral", "voxtral-small-transcribe-3", "it"
    )
    assert [s.text for s in normalized.segments] == ["Buongiorno a tutti", "Sì"]
    assert normalized.segments[1].speaker == "SPEAKER_02"
    assert normalized.segments[1].words[0].text == "Sì"
    assert normalized.raw == {"anything": True}


def test_transcript_without_provider_falls_back_to_the_assembly_language():
    normalized = session_import.parse_transcript({"segments": [{"start": 0, "end": 1, "text": "a"}]}, "de")
    assert normalized.provider == "imported" and normalized.language == "de"


@pytest.mark.parametrize(
    "data, message",
    [
        ([], "must be a JSON object"),
        ({"segments": []}, "no segments"),
        ({"segments": [{"start": "soon", "end": 1, "text": "a"}]}, "non-numeric time"),
        ({"segments": [{"start": 0, "end": 1, "text": 5}]}, "has no text"),
        ({"segments": [{"start": 0, "end": 1, "text": "  "}]}, "Every segment"),
        ({"segments": ["a"]}, "not an object"),
    ],
)
def test_transcript_refusals_say_what_is_wrong(data, message):
    with pytest.raises(session_import.ImportError_, match=message):
        session_import.parse_transcript(data)


def test_attach_allowed_from_the_failed_states_and_nowhere_else():
    for state in session_import.TRANSCRIPT_ATTACHABLE:
        assert state == "TRANSCRIBED" or "TRANSCRIBED" in ALLOWED_TRANSITIONS[state], state
    for state in session_import.AUDIO_ATTACHABLE:
        assert "AUDIO_READY" in ALLOWED_TRANSITIONS[state], state
    # a recording still receiving chunks keeps its own path
    for state in ("CREATED", "RECORDING", "FINALIZING", "WAITING_FOR_CHUNKS", "ASSEMBLING"):
        assert state not in session_import.TRANSCRIPT_ATTACHABLE
        assert state not in session_import.AUDIO_ATTACHABLE


def test_extension_follows_the_mime_type():
    assert session_import.extension_for("audio/mp4") == ".m4a"
    assert session_import.extension_for("audio/webm;codecs=opus") == ".webm"
    assert session_import.extension_for("") == ".webm"


# --- uploads in parts -------------------------------------------------------

def test_upload_is_received_in_parts_and_checked_as_a_whole(settings_env, monkeypatch):
    monkeypatch.setattr(uploads, "PART_BYTES", 4)
    payload = b"0123456789"  # three parts: 4, 4, 2
    meta = uploads.begin("anna", "transcript", "t.json", len(payload))
    assert meta.parts == 3
    with pytest.raises(uploads.UploadError) as refused:
        uploads.store_part(meta.upload_id, "anna", 0, b"012")
    assert refused.value.status == 422
    with pytest.raises(uploads.UploadError) as refused:
        uploads.store_part(meta.upload_id, "anna", 3, b"0123")
    assert refused.value.status == 422
    uploads.store_part(meta.upload_id, "anna", 0, payload[:4])
    uploads.store_part(meta.upload_id, "anna", 2, payload[8:])
    with pytest.raises(uploads.UploadError, match="never arrived"):
        uploads.complete(meta.upload_id, "anna", hashlib.sha256(payload).hexdigest())
    uploads.store_part(meta.upload_id, "anna", 1, payload[4:8])
    with pytest.raises(uploads.UploadError, match="checksum"):
        uploads.complete(meta.upload_id, "anna", "0" * 64)
    with pytest.raises(uploads.UploadError, match="not complete"):
        uploads.take(meta.upload_id, "anna", "transcript")
    done = uploads.complete(meta.upload_id, "anna", hashlib.sha256(payload).hexdigest().upper())
    assert done.complete and done.sha256 == hashlib.sha256(payload).hexdigest()
    path, _ = uploads.take(meta.upload_id, "anna", "transcript")
    assert path.read_bytes() == payload
    with pytest.raises(uploads.UploadError, match="not a session export"):
        uploads.take(meta.upload_id, "anna", "session_export")
    assert uploads.discard(meta.upload_id, "anna")
    with pytest.raises(uploads.UploadError):
        uploads.take(meta.upload_id, "anna", "transcript")


def test_an_upload_belongs_to_the_one_who_opened_it(settings_env):
    meta = uploads.begin("anna", "audio", "a.webm", 3)
    for action in (
        lambda: uploads.store_part(meta.upload_id, "bob", 0, b"abc"),
        lambda: uploads.complete(meta.upload_id, "bob", "0" * 64),
        lambda: uploads.discard(meta.upload_id, "bob"),
    ):
        with pytest.raises(uploads.UploadError) as refused:
            action()
        assert refused.value.status == 404
    with pytest.raises(uploads.UploadError) as refused:
        uploads.take("not-an-id", "anna", "audio")
    assert refused.value.status == 404


def test_upload_refusals(settings_env):
    with pytest.raises(uploads.UploadError, match="empty"):
        uploads.begin("anna", "audio", "a.webm", 0)
    with pytest.raises(uploads.UploadError, match="at most"):
        uploads.begin("anna", "transcript", "t.json", uploads.MAX_BYTES["transcript"] + 1)
    with pytest.raises(uploads.UploadError, match="kind"):
        uploads.begin("anna", "video", "v.mp4", 10)


def test_sweep_forgets_uploads_nobody_finished_within_a_day(settings_env):
    old = uploads.begin("anna", "audio", "a.webm", 3)
    fresh = uploads.begin("anna", "audio", "b.webm", 3)
    assert uploads.sweep_stale(now=time.time() + uploads.UPLOAD_TTL_SECONDS - 60) == 0
    # make only the first one old
    directory, meta = uploads.owned(old.upload_id, "anna")
    meta.created_at -= uploads.UPLOAD_TTL_SECONDS + 1
    uploads._write_meta(directory, meta)
    assert uploads.sweep_stale() == 1
    assert not directory.exists()
    assert uploads.owned(fresh.upload_id, "anna")
