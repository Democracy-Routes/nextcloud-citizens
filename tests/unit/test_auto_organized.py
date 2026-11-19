# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Record now finishes by itself: the idle rule, the honest methodology note
and the readiness test, on minimal rows."""

from datetime import timedelta

from citizens.db.models import Assembly, Finding, Recording, Round, Table
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.services import auto_organized
from citizens.services.report import _methodology_note
from citizens.services.report_text import text


def test_the_idle_rule():
    threshold = auto_organized.idle_threshold_seconds
    assert threshold(1, 0) is None and threshold(3, 0) is None
    assert threshold(1, 10) == 60
    assert threshold(2, 10) == 600
    assert threshold(0, 10) == 600
    assert threshold(5, 1) == 60


def _assembly(session, **fields):
    assembly = Assembly(name="TEST Auto", language="en", created_by="anna", **fields)
    session.add(assembly)
    session.flush()
    round_ = Round(assembly_id=assembly.id, position=1, title="", question="")
    session.add(round_)
    session.flush()
    return assembly, round_


def _finding(session, assembly, round_, reviewed_by, status="APPROVED"):
    finding = Finding(
        assembly_id=assembly.id, round_id=round_.id, scope="table", type="proposal",
        title="T", summary="S", status=status, reviewed_by=reviewed_by,
    )
    session.add(finding)
    session.flush()
    return finding


def _note(session, assembly, findings):
    approved = [f for f in findings if f.status in ("APPROVED", "EDITED_AND_APPROVED")]
    automatic = bool(approved) and all(f.reviewed_by == "system:auto" for f in approved)
    return _methodology_note(session, assembly, reviewed=bool(approved), automatic=automatic)


def test_the_methodology_note_tells_who_reviewed(database):
    with session_scope() as session:
        assembly, round_ = _assembly(session)
        human = _finding(session, assembly, round_, "anna")
        robot = _finding(session, assembly, round_, "system:auto")
        auto_text = text("en", "methodology_automatic")
        human_text = text("en", "methodology_reviewed")
        assert "not reviewed by a person" in auto_text
        # a person reviewed one: the human sentence, never the automatic one
        both = _note(session, assembly, [human, robot])
        assert human_text in both and auto_text not in both
        # only the server approved: the honest sentence
        only_auto = _note(session, assembly, [robot])
        assert auto_text in only_auto and human_text not in only_auto
        # nothing approved: neither
        draft = _finding(session, assembly, round_, None, status="DRAFT")
        neither = _note(session, assembly, [draft])
        assert auto_text not in neither and human_text not in neither


def test_the_automatic_sentence_is_translated():
    english = text("en", "methodology_automatic")
    for language in ("it", "de", "fr", "es"):
        assert text(language, "methodology_automatic") != english


def _recording(session, assembly, round_, state):
    table = Table(round_id=round_.id, number=1) if not round_.tables else round_.tables[0]
    if table.id is None:
        session.add(table)
        session.flush()
        session.refresh(round_)
    recording = Recording(
        assembly_id=assembly.id, round_id=round_.id, table_id=table.id, table_number=1,
        state=state, mime_type="audio/webm",
    )
    session.add(recording)
    session.flush()
    return recording


def test_ready_to_finalize(database):
    now = utcnow()
    with session_scope() as session:
        assembly, round_ = _assembly(session, auto_organized=True)
        _recording(session, assembly, round_, "READY_FOR_REVIEW")
        # not closed
        assert not auto_organized.ready_to_finalize(session, assembly, analysis_on=True)
        assembly.closed_at = now
        # closed, but the round analysis has not landed
        assert not auto_organized.ready_to_finalize(session, assembly, analysis_on=True)
        # analysis off: nothing to wait for
        assert auto_organized.ready_to_finalize(session, assembly, analysis_on=False)
        # analysed
        round_.analysis_summary = "Summary."
        round_.analysis_input_revision = 2
        round_.analysis_applied_revision = 2
        assert auto_organized.ready_to_finalize(session, assembly, analysis_on=True)
        # a review landed after the run: the revision is behind
        round_.analysis_input_revision = 3
        assert not auto_organized.ready_to_finalize(session, assembly, analysis_on=True)
        round_.analysis_input_revision = 2
        # stamped: once
        assembly.auto_finalized_at = now + timedelta(seconds=1)
        assert not auto_organized.ready_to_finalize(session, assembly, analysis_on=True)
        assembly.auto_finalized_at = None
        # a recording still being made
        _recording(session, assembly, round_, "RECORDING")
        assert not auto_organized.ready_to_finalize(session, assembly, analysis_on=True)


def test_a_round_nothing_can_come_from_does_not_wait(database):
    with session_scope() as session:
        assembly, round_ = _assembly(session, auto_organized=True, closed_at=utcnow())
        # no content at all
        assert auto_organized.ready_to_finalize(session, assembly, analysis_on=True)
        _recording(session, assembly, round_, "ANALYSIS_FAILED")
        assert auto_organized.ready_to_finalize(session, assembly, analysis_on=True)


def test_an_organized_assembly_is_never_ready(database):
    with session_scope() as session:
        assembly, _ = _assembly(session, closed_at=utcnow())
        assert not auto_organized.ready_to_finalize(session, assembly, analysis_on=False)
