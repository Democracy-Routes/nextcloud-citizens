# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""An error the adapter did not classify must still show on screen.

`handle_transcribe_final` and `handle_analyze_table` caught only their own
error types. Anything else — a ValueError from a normalizer, a database
error — went straight to the runner: the job ended FAILED, but the recording
kept the state it was in, TRANSCRIBING or ANALYZING, with no error code. The
Files tab showed an in-progress pill forever and offered no button.
"""

import pytest

from citizens.db.models import Assembly, Recording, Round, Table
from citizens.db.session import session_scope
from citizens.jobs import handlers


class MemoryStore:
    def __init__(self, values):
        self.values = values

    def get_value(self, key):
        return self.values.get(key)


def _recording(state):
    with session_scope() as session:
        assembly = Assembly(name="Visibility", created_by="tester")
        session.add(assembly)
        session.flush()
        round_ = Round(assembly_id=assembly.id, position=1, title="R", question="Q")
        session.add(round_)
        session.flush()
        table = Table(round_id=round_.id, number=1)
        session.add(table)
        session.flush()
        recording = Recording(
            assembly_id=assembly.id, round_id=round_.id, table_id=table.id,
            table_number=1, state=state, mime_type="audio/webm",
        )
        session.add(recording)
        session.flush()
        return recording.id


def _state(recording_id):
    with session_scope() as session:
        recording = session.get(Recording, recording_id)
        return recording.state, recording.error_code


def test_an_unclassified_transcription_error_marks_the_recording_failed(database, monkeypatch):
    recording_id = _recording("AUDIO_READY")
    store = MemoryStore({"stt_provider": "mistral", "mistral_api_key": "k"})
    monkeypatch.setattr(handlers.provider_config, "default_store", lambda: store)

    def broken(session, store, recording):
        raise ValueError("could not convert string to float")

    monkeypatch.setattr(handlers.transcription_svc, "transcribe_recording", broken)
    with session_scope() as session, pytest.raises(ValueError):
        handlers.handle_transcribe_final(session, {"recording_id": recording_id})

    assert _state(recording_id) == ("TRANSCRIPTION_FAILED", "TRANSCRIPTION_FAILED")


def test_an_unclassified_analysis_error_marks_the_recording_failed(database, monkeypatch):
    recording_id = _recording("TRANSCRIBED")
    monkeypatch.setattr(handlers.provider_config, "default_store", lambda: object())

    def broken(session, store, recording):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(handlers.analysis_svc, "analyze_table", broken)
    with session_scope() as session, pytest.raises(RuntimeError):
        handlers.handle_analyze_table(session, {"recording_id": recording_id})

    assert _state(recording_id) == ("ANALYSIS_FAILED", "ANALYSIS_FAILED")


def test_a_rate_limited_analysis_says_so(database, monkeypatch):
    from citizens.providers.analysis.openai_compat import AnalysisError

    recording_id = _recording("TRANSCRIBED")
    monkeypatch.setattr(handlers.provider_config, "default_store", lambda: object())

    def throttled(session, store, recording):
        raise AnalysisError("Analysis endpoint returned HTTP 429 (rate limited): x",
                            status=429, retry_after=30)

    monkeypatch.setattr(handlers.analysis_svc, "analyze_table", throttled)
    with session_scope() as session, pytest.raises(AnalysisError):
        handlers.handle_analyze_table(session, {"recording_id": recording_id})

    assert _state(recording_id) == ("ANALYSIS_FAILED", "RATE_LIMITED")
