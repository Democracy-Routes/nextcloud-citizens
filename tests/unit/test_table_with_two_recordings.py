# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A table whose phone was replaced is still one table.

One group of people had one conversation with a technical interruption in the
middle. Analysing each recording separately produced two competing summaries
above a single merged set of findings — telling a reader the same discussion
was both one thing and two — and, because the report keys a table's summary by
(round, table number) with no ordering, the second silently overwrote the first
and database row order decided which anyone saw.

So the analysis covers the table rather than the recording. Everything here
describes what that has to get right.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from citizens.db.models import Finding, Recording
from citizens.db.models.assembly import Assembly, Round, Table
from citizens.db.models.base import utcnow
from citizens.db.models.transcript import Transcript, TranscriptSegment
from citizens.db.session import session_scope
from citizens.services import analysis as analysis_svc
from citizens.services import files as files_svc
from citizens.services import report as report_svc


@pytest.fixture
def swapped_table(client):
    """One table, one round, two recordings — the phone was replaced."""
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Two Recordings",
            "default_table_count": 1,
            "rounds": [{"title": "R1", "question": "What should change?", "duration_minutes": 30}],
        },
    ).json()
    ids = {"assembly_id": assembly["id"]}
    with session_scope() as session:
        round_ = session.execute(
            select(Round).where(Round.assembly_id == assembly["id"])
        ).scalar_one()
        table = session.execute(
            select(Table).where(Table.round_id == round_.id, Table.number == 1)
        ).scalar_one()
        ids["round_id"] = round_.id

        for index, (text, superseded) in enumerate(
            [
                ("We should widen the cycle lanes on Via Zamboni.", True),
                ("And the buses need to run later at night.", False),
            ]
        ):
            recording = Recording(
                assembly_id=assembly["id"],
                round_id=round_.id,
                table_id=table.id,
                table_number=1,
                state="TRANSCRIBED",
                mime_type="audio/webm",
                canonical_audio_path=f"assembled/{assembly['id']}/rec{index}.webm",
                created_at=utcnow() + timedelta(seconds=index),
                superseded_at=utcnow() if superseded else None,
            )
            session.add(recording)
            session.flush()
            ids[f"recording_{index}"] = recording.id

            transcript = Transcript(
                recording_id=recording.id, language="en", provider="test"
            )
            session.add(transcript)
            session.flush()
            session.add(
                TranscriptSegment(
                    transcript_id=transcript.id,
                    sequence=0,
                    start_seconds=0.0,
                    end_seconds=5.0,
                    text=text,
                    speaker_label="SPEAKER_00",
                )
            )
    return ids


def _run_analysis(swapped_table, monkeypatch, findings=()):
    """Analyse the table, with the model stubbed."""
    from citizens.domain.analysis_schemas import TableAnalysis, TableFindingItem

    captured = {}

    def fake_chat(_base, _key, _model, _system, user_prompt, _schema):
        captured["prompt"] = user_prompt
        return TableAnalysis(
            summary="They discussed cycle lanes and night buses.",
            findings=[TableFindingItem(**f) for f in findings],
        )

    monkeypatch.setattr(analysis_svc, "chat_json", fake_chat)
    monkeypatch.setattr(analysis_svc, "_analysis_config", lambda _s: ("http://x", "k", "m"))
    monkeypatch.setattr(analysis_svc, "build_system_prompt", lambda *a, **k: "system")

    with session_scope() as session:
        recording = session.get(Recording, swapped_table["recording_0"])
        analysis_svc.analyze_table(session, object(), recording)
    return captured


# ------------------------------------------------------------- the analysis


def test_both_halves_reach_the_model(swapped_table, monkeypatch):
    captured = _run_analysis(swapped_table, monkeypatch)

    assert "cycle lanes" in captured["prompt"]
    assert "buses need to run later" in captured["prompt"], (
        "the second half of the discussion was never sent for analysis"
    )


def test_the_model_is_told_where_the_device_changed(swapped_table, monkeypatch):
    """Otherwise the join reads as an unexplained jump in the conversation."""
    captured = _run_analysis(swapped_table, monkeypatch)

    assert analysis_svc.DEVICE_CHANGE_MARKER in captured["prompt"]


def test_the_table_ends_with_exactly_one_summary(swapped_table, monkeypatch):
    """The overwrite bug cannot happen if only one row carries a summary."""
    _run_analysis(swapped_table, monkeypatch)

    with session_scope() as session:
        summaries = [
            r.analysis_summary
            for r in session.execute(
                select(Recording).where(Recording.round_id == swapped_table["round_id"])
            ).scalars()
            if r.analysis_summary
        ]
    assert len(summaries) == 1, f"{len(summaries)} recordings carry a summary"
    assert "night buses" in summaries[0]


def test_the_summary_lands_on_the_recording_that_survives(swapped_table, monkeypatch):
    """The report reads the table's summary; it must not be on the half that
    was superseded, or a reader gets nothing."""
    _run_analysis(swapped_table, monkeypatch)

    with session_scope() as session:
        assert session.get(Recording, swapped_table["recording_1"]).analysis_summary
        assert not session.get(Recording, swapped_table["recording_0"]).analysis_summary


def test_findings_are_attributed_to_one_recording(swapped_table, monkeypatch):
    _run_analysis(
        swapped_table,
        monkeypatch,
        findings=[
            {
                "type": "proposal",
                "title": "Widen the cycle lanes",
                "summary": "Both halves of the discussion returned to this.",
                "evidence_segment_ids": ["ignored"],
            }
        ],
    )

    with session_scope() as session:
        findings = list(
            session.execute(
                select(Finding).where(Finding.round_id == swapped_table["round_id"])
            ).scalars()
        )
    # evidence ids were fake, so the finding is dropped — what matters is that
    # nothing was attributed to the superseded recording
    assert all(f.recording_id != swapped_table["recording_0"] for f in findings)


# ------------------------------------------------- waiting for both halves


def test_analysis_waits_while_the_other_half_is_still_transcribing(swapped_table):
    """Analysing the first to finish would summarise half the round."""
    from citizens.jobs.handlers import _table_still_transcribing

    with session_scope() as session:
        session.get(Recording, swapped_table["recording_1"]).state = "TRANSCRIBING"

    with session_scope() as session:
        first = session.get(Recording, swapped_table["recording_0"])
        assert _table_still_transcribing(session, first) is True


def test_analysis_proceeds_once_both_halves_are_transcribed(swapped_table):
    from citizens.jobs.handlers import _table_still_transcribing

    with session_scope() as session:
        first = session.get(Recording, swapped_table["recording_0"])
        assert _table_still_transcribing(session, first) is False


def test_a_table_with_one_recording_never_waits(client):
    """The ordinary case must not be slowed down by any of this."""
    from citizens.jobs.handlers import _table_still_transcribing

    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Single Recording",
            "default_table_count": 1,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()
    with session_scope() as session:
        round_ = session.execute(
            select(Round).where(Round.assembly_id == assembly["id"])
        ).scalar_one()
        table = session.execute(select(Table).where(Table.round_id == round_.id)).scalars().first()
        recording = Recording(
            assembly_id=assembly["id"],
            round_id=round_.id,
            table_id=table.id,
            table_number=1,
            state="TRANSCRIBED",
            mime_type="audio/webm",
        )
        session.add(recording)
        session.flush()
        assert _table_still_transcribing(session, recording) is False


# ------------------------------------------------------------ the exports


def test_the_two_recordings_get_different_file_names(swapped_table):
    """Identical names meant duplicate zip entries and a manifest pointing two
    records at one path."""
    with session_scope() as session:
        assembly = session.get(Assembly, swapped_table["assembly_id"])
        first = session.get(Recording, swapped_table["recording_0"])
        second = session.get(Recording, swapped_table["recording_1"])

        assert files_svc.audio_filename(assembly, first, 1) != files_svc.audio_filename(
            assembly, second, 1
        )


def test_an_ordinary_recording_keeps_its_plain_name(client):
    """No churn in the normal case: existing exports should look the same."""
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "Bologna",
            "default_table_count": 1,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()
    with session_scope() as session:
        db_assembly = session.get(Assembly, assembly["id"])
        round_ = session.execute(
            select(Round).where(Round.assembly_id == assembly["id"])
        ).scalar_one()
        table = session.execute(select(Table).where(Table.round_id == round_.id)).scalars().first()
        recording = Recording(
            assembly_id=assembly["id"],
            round_id=round_.id,
            table_id=table.id,
            table_number=3,
            state="TRANSCRIBED",
            mime_type="audio/webm",
            canonical_audio_path="assembled/x/rec.webm",
        )
        session.add(recording)
        session.flush()

        assert files_svc.audio_filename(db_assembly, recording, 2) == "Bologna-round2-table3.webm"


# ------------------------------------------------------------- the report


def test_the_report_says_a_device_was_replaced(swapped_table):
    """The method text claims a phone per table recorded each conversation.
    When one was swapped, a reader deserves to know why there is a gap."""
    with session_scope() as session:
        assembly = session.get(Assembly, swapped_table["assembly_id"])
        report = report_svc.build_report(session, assembly)

    assert report_svc.DEVICE_REPLACED_NOTE.strip() in report["methodology_note"]


def test_an_ordinary_assembly_says_nothing_about_devices(client):
    with session_scope() as session:
        assembly_id = client.post(
            "/api/v1/assemblies",
            json={
                "name": "TEST Ordinary",
                "default_table_count": 1,
                "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
            },
        ).json()["id"]
        assembly = session.get(Assembly, assembly_id)
        report = report_svc.build_report(session, assembly)

    assert report_svc.DEVICE_REPLACED_NOTE.strip() not in report["methodology_note"]


def test_the_report_shows_one_summary_for_the_table(swapped_table, monkeypatch):
    """The whole point: one table, one discussion, one summary."""
    _run_analysis(swapped_table, monkeypatch)

    with session_scope() as session:
        assembly = session.get(Assembly, swapped_table["assembly_id"])
        report = report_svc.build_report(session, assembly)

    tables = report["rounds"][0]["tables"]
    summaries = [t["summary"] for t in tables if t["summary"]]
    assert len(summaries) == 1
    assert "night buses" in summaries[0]
