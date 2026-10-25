# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A transcript says where it came from: live captions or the finished audio,
which engine, which model, which phone — and which record is canonical.

Live captions and final transcription are independent switches, so a
recording's transcript of record may be either. The rule is stated rather than
inferred: the Transcript row is canonical, one per recording, and a final
transcription replaces a live one deterministically.
"""

import pytest
from sqlalchemy import select

from citizens.db.models import Assembly, Recording, Round, Table, Transcript, TranscriptSegment
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.providers.transcription.base import NormalizedSegment, NormalizedTranscript
from citizens.services import report as report_svc
from citizens.services import transcription as transcription_svc


@pytest.fixture
def recorded(client):
    """One table, one round, one recording that reached TRANSCRIBED."""
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST provenance", "default_table_count": 1, "language": "en",
            "rounds": [{"title": "R1", "question": "Q", "duration_minutes": 30}],
        },
    ).json()
    with session_scope() as session:
        round_ = session.execute(select(Round).where(Round.assembly_id == assembly["id"])).scalar_one()
        table = session.execute(select(Table).where(Table.round_id == round_.id)).scalar_one()
        recording = Recording(
            assembly_id=assembly["id"], round_id=round_.id, table_id=table.id, table_number=1,
            state="TRANSCRIBED", mime_type="audio/webm",
            canonical_audio_path=f"assembled/{assembly['id']}/rec.webm", started_at=utcnow(),
        )
        session.add(recording)
        session.flush()
        recording_id = recording.id
    return {"client": client, "assembly_id": assembly["id"], "recording_id": recording_id}


def _live_transcript(recording_id):
    with session_scope() as session:
        transcript = Transcript(
            recording_id=recording_id, provider="vosk", model="vosk-model-small-en-us-0.15",
            language="en", source="live",
        )
        session.add(transcript)
        session.flush()
        session.add(TranscriptSegment(
            transcript_id=transcript.id, sequence=0, start_seconds=0.0, end_seconds=4.0,
            text="we need later buses", speaker_label="SPEAKER_01",
        ))
        return transcript.id


def test_a_live_transcript_is_marked_live_with_its_engine_and_phone(recorded):
    _live_transcript(recorded["recording_id"])
    payload = recorded["client"].get(f"/api/v1/recordings/{recorded['recording_id']}/transcript").json()
    provenance = payload["provenance"]
    assert provenance["source_type"] == "live"
    assert provenance["provider"] == "vosk"
    assert provenance["model"] == "vosk-model-small-en-us-0.15"
    assert provenance["language"] == "en"
    assert provenance["recording_id"] == recorded["recording_id"]
    assert provenance["canonical"] is True
    assert provenance["created_at"]
    assert (provenance["recorder_slot"], provenance["recorder_label"]) == (1, "A")
    assert provenance["live_captions_available"] is False
    # the same statement on the Files tab
    files = recorded["client"].get(f"/api/v1/assemblies/{recorded['assembly_id']}/files").json()
    [entry] = files["rounds"][0]["tables"]
    assert entry["transcript_source"] == "live"
    assert entry["transcript_provenance"]["source_type"] == "live"
    assert entry["transcript_provenance"]["provider"] == "vosk"


def test_a_final_transcription_replaces_the_live_record_and_stays_the_only_one(recorded):
    live_id = _live_transcript(recorded["recording_id"])
    final = NormalizedTranscript(
        provider="deepgram", model="nova-3", language="en",
        segments=[NormalizedSegment(speaker="SPEAKER_01", start=0.0, end=4.2, text="We need later buses.")],
        raw={},
    )
    with session_scope() as session:
        recording = session.get(Recording, recorded["recording_id"])
        transcription_svc.store_transcript(session, recording, final, source="final")

    with session_scope() as session:
        rows = list(session.execute(
            select(Transcript).where(Transcript.recording_id == recorded["recording_id"])
        ).scalars())
        assert len(rows) == 1 and rows[0].id != live_id
    provenance = recorded["client"].get(
        f"/api/v1/recordings/{recorded['recording_id']}/transcript"
    ).json()["provenance"]
    assert provenance["source_type"] == "final"
    assert (provenance["provider"], provenance["model"]) == ("deepgram", "nova-3")
    assert provenance["canonical"] is True


def test_the_report_states_the_engines_and_flags_live_captions(recorded):
    _live_transcript(recorded["recording_id"])
    with session_scope() as session:
        assembly = session.get(Assembly, recorded["assembly_id"])
        report = report_svc.build_report(session, assembly)
    note = report["methodology_note"]
    assert "Speech-to-text: vosk vosk-model-small-en-us-0.15 (live captions)." in note
    assert "live captions produced while" in note
    assert "Speech-to-text:" in report_svc.render_markdown(report)


def test_a_recording_without_a_transcript_says_so(recorded):
    files = recorded["client"].get(f"/api/v1/assemblies/{recorded['assembly_id']}/files").json()
    [entry] = files["rounds"][0]["tables"]
    assert entry["has_transcript"] is False
    assert entry["transcript_provenance"] is None
    with session_scope() as session:
        assembly = session.get(Assembly, recorded["assembly_id"])
        assert "Speech-to-text:" not in report_svc.build_report(session, assembly)["methodology_note"]
