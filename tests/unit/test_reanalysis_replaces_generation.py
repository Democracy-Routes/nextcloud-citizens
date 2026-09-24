# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A re-analysis replaces the whole generation of findings, reviews included.

Until 2026-09-24 approved and hand-edited findings survived a re-run, so the
next generation was added next to them. At that day's rehearsal the organizer
approved everything, pressed "Re-run analysis", and the report printed every
theme twice: 6 + 6 findings for one table, 10 + 11 cross-table clusters, each
pair worded a little differently. A table's findings are a function of its
transcript and the round's clusters a function of the table findings; a new
run replaces the old one.

The one exception is a re-run that comes back EMPTY over a table that had
findings — the same rehearsal produced that too, five findings then none on
an unchanged transcript. That is the model's inconsistency, not information,
and it must not wipe the only good analysis of a table.
"""

import pytest
from sqlalchemy import select

from citizens.db.models import Finding
from citizens.db.models.assembly import Assembly, Round, Table
from citizens.db.models.recording import Recording
from citizens.db.session import session_scope
from citizens.domain.analysis_schemas import (
    RoundAnalysis,
    RoundClusterItem,
    TableAnalysis,
    TableFindingItem,
)
from citizens.jobs import handlers
from citizens.services import analysis as analysis_svc
from citizens.services import job_failures
from citizens.services.analysis import AnalysisError


@pytest.fixture
def seeded(client, settings_env):
    """One transcribed table with an APPROVED, an EDITED_AND_APPROVED and a
    DRAFT finding, and an APPROVED cross-table cluster built on the first."""
    from citizens.db.models.transcript import Transcript, TranscriptSegment

    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Re-analysis",
            "default_table_count": 1,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()
    with session_scope() as session:
        db_assembly = session.get(Assembly, assembly["id"])
        round_ = session.execute(
            select(Round).where(Round.assembly_id == db_assembly.id)
        ).scalar_one()
        table = session.execute(
            select(Table).where(Table.round_id == round_.id, Table.number == 1)
        ).scalar_one()
        recording = Recording(
            assembly_id=db_assembly.id,
            round_id=round_.id,
            table_id=table.id,
            table_number=1,
            state="READY_FOR_REVIEW",
            mime_type="audio/webm",
            analysis_summary="The first run's summary.",
        )
        session.add(recording)
        session.flush()
        transcript = Transcript(recording_id=recording.id, language="en", provider="test")
        session.add(transcript)
        session.flush()
        segment = TranscriptSegment(
            transcript_id=transcript.id,
            sequence=0,
            start_seconds=0.0,
            end_seconds=4.0,
            text="We should widen the cycle lanes on Via Zamboni.",
            speaker_label="SPEAKER_01",
        )
        session.add(segment)
        session.flush()
        old = []
        for status, title in (
            ("APPROVED", "Widen the cycle lanes"),
            ("EDITED_AND_APPROVED", "Widen the cycle lanes (edited by hand)"),
            ("DRAFT", "A draft nobody reviewed"),
        ):
            finding = Finding(
                assembly_id=db_assembly.id,
                round_id=round_.id,
                table_id=table.id,
                recording_id=recording.id,
                scope="table",
                type="proposal",
                title=title,
                summary="Cycle lanes.",
                status=status,
            )
            session.add(finding)
            old.append(finding)
        session.flush()
        cluster = Finding(
            assembly_id=db_assembly.id,
            round_id=round_.id,
            scope="round",
            type="proposal",
            title="An approved cross-table cluster",
            summary="Every table wants cycle lanes.",
            status="APPROVED",
            source_finding_ids=f'["{old[0].id}"]',
            mentioned_table_count=1,
        )
        session.add(cluster)
        session.flush()
        return {
            "assembly_id": db_assembly.id,
            "round_id": round_.id,
            "recording_id": recording.id,
            "segment_id": segment.id,
            "table_finding_id": old[0].id,
        }


def _stub_model(monkeypatch, answer):
    monkeypatch.setattr(analysis_svc, "chat_json", lambda *_a, **_k: answer)
    monkeypatch.setattr(analysis_svc, "_analysis_config", lambda _store: ("http://x", "k", "m"))
    monkeypatch.setattr(analysis_svc, "build_system_prompt", lambda *_a, **_k: "system prompt")


def _table_titles(recording_id):
    with session_scope() as session:
        return sorted(
            session.execute(
                select(Finding.title).where(
                    Finding.recording_id == recording_id, Finding.scope == "table"
                )
            ).scalars()
        )


def _cluster_titles(round_id):
    with session_scope() as session:
        return sorted(
            session.execute(
                select(Finding.title).where(Finding.round_id == round_id, Finding.scope == "round")
            ).scalars()
        )


def _fresh_table_answer(segment_id):
    return TableAnalysis(
        summary="The second run's summary of the same discussion.",
        findings=[
            TableFindingItem(
                type="proposal",
                title="Fresh finding from the second run",
                summary="Cycle lanes, again.",
                evidence_segment_ids=[segment_id],
            )
        ],
    )


def test_a_rerun_replaces_approved_and_edited_findings_too(seeded, monkeypatch):
    _stub_model(monkeypatch, _fresh_table_answer(seeded["segment_id"]))

    with session_scope() as session:
        recording = session.get(Recording, seeded["recording_id"])
        stored = analysis_svc.analyze_table(session, object(), recording)

    assert stored == 1
    assert _table_titles(seeded["recording_id"]) == ["Fresh finding from the second run"], (
        "the previous generation survived the re-run — the report would print "
        "both generations side by side, which is exactly what the 24 September "
        "rehearsal produced"
    )
    with session_scope() as session:
        recording = session.get(Recording, seeded["recording_id"])
        assert recording.analysis_summary == "The second run's summary of the same discussion."


def test_reclustering_replaces_approved_clusters_too(seeded, monkeypatch):
    _stub_model(
        monkeypatch,
        RoundAnalysis(
            summary="A fresh overview of the round.",
            clusters=[
                RoundClusterItem(
                    type="proposal",
                    title="Fresh cluster",
                    summary="Cycle lanes across tables.",
                    source_finding_ids=[seeded["table_finding_id"]],
                )
            ],
        ),
    )

    with session_scope() as session:
        round_ = session.get(Round, seeded["round_id"])
        stored = analysis_svc.analyze_round(session, object(), round_)

    assert stored == 1
    assert _cluster_titles(seeded["round_id"]) == ["Fresh cluster"]


def test_an_empty_rerun_keeps_the_previous_generation_and_says_so(seeded, monkeypatch):
    _stub_model(monkeypatch, TableAnalysis(summary="Nothing to report this time.", findings=[]))

    with session_scope() as session:
        recording = session.get(Recording, seeded["recording_id"])
        with pytest.raises(AnalysisError) as raised:
            analysis_svc.analyze_table(session, object(), recording)

    assert raised.value.permanent, "a retry would only ask the same model the same question"
    assert job_failures.classify(str(raised.value)) == "RERUN_EMPTY"
    assert len(_table_titles(seeded["recording_id"])) == 3
    with session_scope() as session:
        recording = session.get(Recording, seeded["recording_id"])
        assert recording.analysis_summary == "The first run's summary.", (
            "the summary was replaced while the findings were kept — the "
            "table would describe one analysis and list another"
        )


def test_findings_dropped_for_bad_evidence_count_as_an_empty_rerun(seeded, monkeypatch):
    """A run whose every finding cites invented segment ids stores nothing
    either; the guard must look at what would be stored, not at what the
    model claimed to find."""
    _stub_model(
        monkeypatch,
        TableAnalysis(
            summary="Confident, and wrong about every id.",
            findings=[
                TableFindingItem(
                    type="proposal",
                    title="Cites a segment that does not exist",
                    summary="Cycle lanes, with invented evidence.",
                    evidence_segment_ids=["not-a-real-segment"],
                )
            ],
        ),
    )

    with session_scope() as session:
        recording = session.get(Recording, seeded["recording_id"])
        with pytest.raises(AnalysisError):
            analysis_svc.analyze_table(session, object(), recording)

    assert len(_table_titles(seeded["recording_id"])) == 3


def test_a_first_run_with_no_findings_is_stored_normally(seeded, monkeypatch):
    """The guard is about losing a generation; a table that never had one
    simply records that the discussion held nothing substantive."""
    with session_scope() as session:
        for finding in session.execute(
            select(Finding).where(Finding.recording_id == seeded["recording_id"])
        ).scalars():
            session.delete(finding)
    _stub_model(monkeypatch, TableAnalysis(summary="They talked about the weather.", findings=[]))

    with session_scope() as session:
        recording = session.get(Recording, seeded["recording_id"])
        assert analysis_svc.analyze_table(session, object(), recording) == 0

    with session_scope() as session:
        recording = session.get(Recording, seeded["recording_id"])
        assert recording.analysis_summary == "They talked about the weather."


def test_a_rejected_finding_does_not_protect_an_empty_rerun(seeded, monkeypatch):
    """REJECTED is the organizer saying the finding was wrong; a table whose
    only findings were rejected has no generation worth keeping."""
    with session_scope() as session:
        for finding in session.execute(
            select(Finding).where(
                Finding.recording_id == seeded["recording_id"], Finding.scope == "table"
            )
        ).scalars():
            finding.status = "REJECTED"
    _stub_model(monkeypatch, TableAnalysis(summary="Nothing this time.", findings=[]))

    with session_scope() as session:
        recording = session.get(Recording, seeded["recording_id"])
        assert analysis_svc.analyze_table(session, object(), recording) == 0

    assert _table_titles(seeded["recording_id"]) == []


def test_the_handler_shows_an_empty_rerun_as_a_failed_job_with_the_findings_intact(
    seeded, monkeypatch
):
    """What the organizer sees: the table's failure note says the previous
    findings were kept, and the report still carries them."""
    _stub_model(monkeypatch, TableAnalysis(summary="Nothing to report this time.", findings=[]))
    monkeypatch.setattr(handlers.provider_config, "default_store", lambda: object())

    with session_scope() as session:
        with pytest.raises(handlers.PermanentJobError, match="returned no findings"):
            handlers.handle_analyze_table(
                session, {"recording_id": seeded["recording_id"], "force": True}
            )

    with session_scope() as session:
        recording = session.get(Recording, seeded["recording_id"])
        assert recording.state == "ANALYSIS_FAILED"
    assert len(_table_titles(seeded["recording_id"])) == 3
    assert len(_cluster_titles(seeded["round_id"])) == 1, (
        "a refused re-run must not trigger a re-clustering either"
    )
