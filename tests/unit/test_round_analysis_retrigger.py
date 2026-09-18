# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cross-table clustering re-runs when — and only when — its inputs moved.

A SUCCEEDED round job is not proof the clusters are current: rejecting or
editing a finding changes what the clustering reads, and before this no review
of any kind re-clustered, so the report's cross-table section went stale
silently. Two counters on the round decide it now (services/round_analysis):
input bumps on every change, applied is what a run started from. A review
landing mid-run gets exactly one follow-up; further changes coalesce.

The review half is exercised through the REAL routes — a helper that works in
isolation while the endpoints never call it is precisely the shape of the bug
this replaces.
"""

import json

import pytest
from sqlalchemy import select

from citizens.db.models import AppJob, Assembly, Finding, Recording, Round, Table
from citizens.db.session import session_scope
from citizens.jobs import handlers
from citizens.jobs.handlers import maybe_enqueue_round_analysis
from citizens.services import round_analysis
from citizens.services.jobs import LIVE_JOB_STATES, enqueue_job


def _seed(session, owner="tester"):
    assembly = Assembly(name="Clustering", created_by=owner)
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
        table_number=1, state="READY_FOR_REVIEW",
    )
    session.add(recording)
    session.flush()
    finding = Finding(
        assembly_id=assembly.id, round_id=round_.id, table_id=table.id,
        scope="table", type="proposal", title="Widen the lanes", summary="s",
    )
    session.add(finding)
    session.flush()
    return {"assembly": assembly.id, "round": round_.id,
            "recording": recording.id, "finding": finding.id}


@pytest.fixture
def seeded(database):
    with session_scope() as session:
        return _seed(session)


def _round_jobs(session, round_id, states=None):
    jobs = session.scalars(select(AppJob).where(AppJob.type == "ANALYZE_ROUND"))
    found = []
    for job in jobs:
        if json.loads(job.payload_json).get("round_id") != round_id:
            continue
        if states is None or job.state in states:
            found.append(job)
    return found


def _revisions(session, round_id):
    round_ = session.get(Round, round_id)
    return round_.analysis_input_revision, round_.analysis_applied_revision


# -------------------------------------------------------------- the gate


def test_first_completion_enqueues_at_the_new_revision(seeded):
    with session_scope() as session:
        maybe_enqueue_round_analysis(session, session.get(Recording, seeded["recording"]))
        jobs = _round_jobs(session, seeded["round"])
        assert len(jobs) == 1 and jobs[0].state == "QUEUED"
        assert json.loads(jobs[0].payload_json)["revision"] == 1
        assert _revisions(session, seeded["round"]) == (1, 0)


def test_a_queued_job_absorbs_later_changes(seeded):
    with session_scope() as session:
        maybe_enqueue_round_analysis(session, session.get(Recording, seeded["recording"]))
        # more changes before it starts: it will read them all when it does
        round_analysis.bump_round_inputs(session, seeded["round"])
        assert round_analysis.enqueue_round_analysis_if_stale(session, seeded["round"]) is False
        assert len(_round_jobs(session, seeded["round"])) == 1


def test_a_run_that_consumed_the_inputs_does_not_rerun(seeded):
    with session_scope() as session:
        round_ = session.get(Round, seeded["round"])
        round_.analysis_input_revision = 3
        round_.analysis_applied_revision = 3
        assert round_analysis.enqueue_round_analysis_if_stale(session, seeded["round"]) is False
        assert _round_jobs(session, seeded["round"]) == []


def test_a_change_during_a_run_queues_exactly_one_follow_up(seeded):
    """The run in flight started from revision 1 and cannot see revision 2;
    one follow-up queues. A third change coalesces into that follow-up."""
    with session_scope() as session:
        round_ = session.get(Round, seeded["round"])
        round_.analysis_input_revision = 1
        running = enqueue_job(session, "ANALYZE_ROUND", {"round_id": seeded["round"], "revision": 1})
        running.state = "RUNNING"
        session.flush()

        round_analysis.bump_round_inputs(session, seeded["round"])  # -> 2
        assert round_analysis.enqueue_round_analysis_if_stale(session, seeded["round"]) is True
        round_analysis.bump_round_inputs(session, seeded["round"])  # -> 3
        assert round_analysis.enqueue_round_analysis_if_stale(session, seeded["round"]) is False

        queued = _round_jobs(session, seeded["round"], states=("QUEUED",))
        assert len(queued) == 1, "a mid-run change must queue one follow-up, not zero, not two"


def test_a_pending_table_holds_the_run_back(seeded):
    """A table still transcribing owes its findings: whichever completion
    lands last re-enters with a higher revision and queues the run that
    sees everything."""
    with session_scope() as session:
        r = session.get(Recording, seeded["recording"])
        r.state = "TRANSCRIBING"
        round_analysis.bump_round_inputs(session, seeded["round"])
        assert round_analysis.enqueue_round_analysis_if_stale(session, seeded["round"]) is False
        r.state = "READY_FOR_REVIEW"
        assert round_analysis.enqueue_round_analysis_if_stale(session, seeded["round"]) is True


def test_the_handler_stamps_what_it_read_and_records_what_it_applied(seeded, monkeypatch):
    monkeypatch.setattr(handlers.analysis_svc, "analyze_round", lambda *a, **k: 0)
    monkeypatch.setattr(handlers.provider_config, "default_store", lambda: object())
    with session_scope() as session:
        round_ = session.get(Round, seeded["round"])
        round_.analysis_input_revision = 4
        running = enqueue_job(session, "ANALYZE_ROUND", {"round_id": seeded["round"]})
        running.state = "RUNNING"
        session.flush()

        handlers.handle_analyze_round(session, {"round_id": seeded["round"]})

        assert json.loads(running.payload_json)["revision"] == 4, "the run did not stamp its revision"
        assert _revisions(session, seeded["round"]) == (4, 4)


# ---------------------------------------------- through the real review routes


def _live(session, round_id):
    return _round_jobs(session, round_id, states=LIVE_JOB_STATES)


def test_rejecting_a_finding_reclusters(client):
    with session_scope() as session:
        ids = _seed(session)
    response = client.put(f"/api/v1/findings/{ids['finding']}", json={"status": "REJECTED"})
    assert response.status_code == 200, response.text
    with session_scope() as session:
        assert len(_live(session, ids["round"])) == 1, "rejecting never re-clustered"
        assert _revisions(session, ids["round"])[0] == 1


def test_editing_a_finding_reclusters(client):
    with session_scope() as session:
        ids = _seed(session)
    response = client.put(
        f"/api/v1/findings/{ids['finding']}", json={"title": "Widen the cycle lanes"}
    )
    assert response.status_code == 200, response.text
    with session_scope() as session:
        assert len(_live(session, ids["round"])) == 1


def test_approving_alone_does_not_recluster(client):
    """Approval changes nothing the clustering reads (it takes every finding
    that is not rejected), so re-running would only spend a model call."""
    with session_scope() as session:
        ids = _seed(session)
    assert client.put(f"/api/v1/findings/{ids['finding']}", json={"status": "APPROVED"}).status_code == 200
    assert client.post(f"/api/v1/rounds/{ids['round']}/findings/approve", json={}).status_code == 200
    with session_scope() as session:
        assert _live(session, ids["round"]) == []
        assert _revisions(session, ids["round"]) == (0, 0)


def test_a_review_landing_mid_run_is_not_lost(client):
    """The race the counters exist for: the organizer rejects a finding while
    the round job is RUNNING. That run cannot see it — one follow-up queues."""
    with session_scope() as session:
        ids = _seed(session)
        round_ = session.get(Round, ids["round"])
        round_.analysis_input_revision = 1
        running = enqueue_job(session, "ANALYZE_ROUND", {"round_id": ids["round"], "revision": 1})
        running.state = "RUNNING"
    assert client.put(f"/api/v1/findings/{ids['finding']}", json={"status": "REJECTED"}).status_code == 200
    with session_scope() as session:
        queued = _round_jobs(session, ids["round"], states=("QUEUED", "RETRY"))
        assert len(queued) == 1
