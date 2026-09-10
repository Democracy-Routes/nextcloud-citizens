# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Intentional erasure must survive recovery sweeps and stale jobs."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from citizens.db.models import AppJob, Assembly, Recording, Round, Table, Transcript
from citizens.db.session import configure_database, session_scope, sqlite_url
from citizens.jobs import handlers, sweep
from citizens.main import create_app
from citizens.security.identity import get_current_user_id
from citizens.services import files, provider_config, transcription
from citizens.services.jobs import enqueue_job


@pytest.fixture
def recordings(database):
    with session_scope() as session:
        assembly = Assembly(name="Deletion", created_by="tester")
        session.add(assembly)
        session.flush()
        round_ = Round(assembly_id=assembly.id, position=1, title="Round", question="Question")
        session.add(round_)
        session.flush()
        table = Table(round_id=round_.id, number=1)
        session.add(table)
        session.flush()
        ids = []
        for index in range(2):
            audio = database.app_persistent_storage / f"audio-{index}.webm"
            audio.write_bytes(b"audio")
            raw = database.app_persistent_storage / f"raw-{index}.json"
            raw.write_text('{}')
            recording = Recording(
                assembly_id=assembly.id, round_id=round_.id, table_id=table.id,
                table_number=1, state="TRANSCRIBED", canonical_audio_path=audio.name,
            )
            session.add(recording)
            session.flush()
            session.add(Transcript(recording_id=recording.id, provider="test", raw_response_path=raw.name))
            ids.append(recording.id)
        return assembly.id, ids


@pytest.fixture
def api_client(recordings):
    # The database fixture owns startup; no background worker can race these assertions.
    app = create_app(with_auth=False)
    app.dependency_overrides[get_current_user_id] = lambda: "tester"
    return TestClient(app)


def test_deletion_survives_sweeps_and_database_reconnect(recordings, api_client, database, monkeypatch):
    _, ids = recordings
    monkeypatch.setattr(provider_config, "default_store", lambda: object())
    monkeypatch.setattr(transcription, "batch_transcription_ready", lambda _: True)
    monkeypatch.setattr(transcription, "live_transcription_ready", lambda _: True)
    monkeypatch.setattr(handlers, "_maybe_enqueue_analysis", lambda *_: None)
    assert api_client.delete(f"/api/v1/recordings/{ids[0]}/transcript").status_code == 200
    configure_database(sqlite_url(database.app_persistent_storage / "citizens.db"))
    for _ in range(2):
        sweep.sweep_missed_enqueues()
    with session_scope() as session:
        assert session.get(Recording, ids[0]).transcript_deleted_at is not None
        assert list(session.scalars(select(AppJob))) == []
        assert session.scalar(select(Transcript).where(Transcript.recording_id == ids[0])) is None
    assert api_client.post(f"/api/v1/recordings/{ids[0]}/transcribe").status_code == 202
    with session_scope() as session:
        assert session.get(Recording, ids[0]).transcript_deleted_at is None
        assert session.scalar(select(AppJob)).type == "TRANSCRIBE_FINAL"


@pytest.mark.parametrize("kind", ["TRANSCRIBE_FINAL", "TRANSCRIBE_FROM_LIVE"])
@pytest.mark.parametrize("state", ["QUEUED", "RUNNING", "RETRY"])
def test_deletion_conflicts_are_atomic(recordings, api_client, database, kind, state):
    assembly_id, ids = recordings
    with session_scope() as session:
        job = enqueue_job(session, kind, {"recording_id": ids[1]})
        job.state = state
    assert api_client.delete(f"/api/v1/recordings/{ids[1]}/transcript").status_code == 409
    assert api_client.delete(f"/api/v1/assemblies/{assembly_id}/transcripts").status_code == 409
    with session_scope() as session:
        assert len(list(session.scalars(select(Transcript)))) == 2
        assert all(session.get(Recording, rid).transcript_deleted_at is None for rid in ids)
    assert (database.app_persistent_storage / "raw-0.json").exists()
    assert (database.app_persistent_storage / "raw-1.json").exists()


@pytest.mark.parametrize("handler", [handlers.handle_transcribe_final, handlers.handle_transcribe_from_live])
def test_stale_jobs_cannot_override_deletion(recordings, handler):
    with session_scope() as session:
        recording = session.get(Recording, recordings[1][0])
        files.delete_recording_transcript(session, recording)
        with pytest.raises(handlers.PermanentJobError, match="deliberately deleted"):
            handler(session, {"recording_id": recording.id, "force": True})


def test_deletion_during_config_read_prevents_enqueue(recordings, monkeypatch):
    rid = recordings[1][0]

    def delete_during_config(_):
        with session_scope() as other:
            files.delete_recording_transcript(other, other.get(Recording, rid))
        return True

    monkeypatch.setattr(provider_config, "default_store", lambda: object())
    monkeypatch.setattr(transcription, "batch_transcription_ready", delete_during_config)
    monkeypatch.setattr(transcription, "live_transcription_ready", lambda _: False)
    with session_scope() as session:
        handlers._maybe_enqueue_transcription(session, session.get(Recording, rid))
    with session_scope() as session:
        assert list(session.scalars(select(AppJob))) == []


def test_deleted_sibling_does_not_block_analysis(recordings):
    with session_scope() as session:
        deleted, sibling = [session.get(Recording, rid) for rid in recordings[1]]
        files.delete_recording_transcript(session, deleted)
        sibling.state = "READY_FOR_REVIEW"
        assert not handlers._table_still_transcribing(session, sibling)
        handlers.maybe_enqueue_round_analysis(session, sibling)
        assert session.scalar(select(AppJob)).type == "ANALYZE_ROUND"


def test_rejected_manual_request_preserves_deletion(recordings, api_client, database):
    rid = recordings[1][0]
    assert api_client.delete(f"/api/v1/recordings/{rid}/transcript").status_code == 200
    (database.app_persistent_storage / "audio-0.webm").unlink()
    assert api_client.post(f"/api/v1/recordings/{rid}/transcribe").status_code == 409
    with session_scope() as session:
        assert session.get(Recording, rid).transcript_deleted_at is not None
        assert list(session.scalars(select(AppJob))) == []


def test_migration_preserves_existing_recordings(recordings, database):
    cfg = Config()
    cfg.set_main_option("script_location", str(Path("citizens/db/migrations").resolve()))
    cfg.set_main_option("sqlalchemy.url", sqlite_url(database.app_persistent_storage / "citizens.db"))
    command.downgrade(cfg, "0018")
    command.upgrade(cfg, "head")
    with session_scope() as session:
        assert all(session.get(Recording, rid).transcript_deleted_at is None for rid in recordings[1])
        for rid in recordings[1]:
            recording = session.get(Recording, rid)
            assert recording.audio_manifest_sha256 is None
            assert recording.audio_manifest_bytes is None
            assert (database.app_persistent_storage / recording.canonical_audio_path).is_file()
