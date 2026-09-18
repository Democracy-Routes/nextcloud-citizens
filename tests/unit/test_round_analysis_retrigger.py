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


# ------------------------------------ what the organizer sees, and can stop


def _future(seconds):
    from datetime import timedelta

    from citizens.db.models.base import utcnow

    return utcnow() + timedelta(seconds=seconds)


@pytest.fixture
def analysis_configured(monkeypatch):
    """GET /rounds/{id}/findings reports whether analysis is configured, which
    reads the Nextcloud config store; these tests are about the payload, not
    the store."""
    from citizens.api import findings as findings_api

    monkeypatch.setattr(findings_api, "analysis_ready", lambda store: True)
    monkeypatch.setattr(findings_api.provider_config, "default_store", lambda: object())


def test_round_findings_carry_the_last_jobs_reason(client, analysis_configured):
    """2026-09-18: a 403 was re-run five times because the tab said only
    "did not complete". The payload now carries the job's classified reason
    and the provider's words, per table and for the clustering."""
    with session_scope() as session:
        ids = _seed(session)
        recording = session.get(Recording, ids["recording"])
        recording.state = "ANALYSIS_FAILED"
        recording.error_code = "ANALYSIS_FAILED"
        job = enqueue_job(session, "ANALYZE_TABLE", {"recording_id": ids["recording"], "force": True})
        job.state = "FAILED"
        job.last_error = "Analysis authentication failed (403): Inactive subscription or usage limit"
        round_job = enqueue_job(session, "ANALYZE_ROUND", {"round_id": ids["round"], "revision": 1})
        round_job.state = "FAILED"
        round_job.last_error = "Model output failed validation after retries: clusters.0.title"
    body = client.get(f"/api/v1/rounds/{ids['round']}/findings").json()
    table = body["tables"][0]
    assert table["recording"]["error_code"] == "ANALYSIS_FAILED"
    assert table["recording"]["job"]["state"] == "FAILED"
    assert table["recording"]["job"]["failure_reason"] == "PROVIDER_AUTH"
    assert "Inactive subscription" in table["recording"]["job"]["failure_detail"]
    assert body["round_job"]["state"] == "FAILED"
    assert body["round_job"]["failure_reason"] == "SCHEMA_INVALID"


def test_a_table_waiting_for_its_retry_says_so(client, analysis_configured):
    with session_scope() as session:
        ids = _seed(session)
        recording = session.get(Recording, ids["recording"])
        recording.state = "ANALYZING"
        job = enqueue_job(session, "ANALYZE_TABLE", {"recording_id": ids["recording"]})
        job.state = "RETRY"
        job.attempts = 2
        job.next_attempt_at = _future(90)
        job.last_error = "Analysis endpoint returned HTTP 429 (rate limited): slow down"
    body = client.get(f"/api/v1/rounds/{ids['round']}/findings").json()
    job_info = body["tables"][0]["recording"]["job"]
    assert job_info["state"] == "RETRY" and job_info["attempts"] == 2
    assert job_info["failure_reason"] == "PROVIDER_RATE_LIMIT"
    assert job_info["next_attempt_at"] is not None


def test_cancel_stops_queued_and_retrying_jobs_but_not_a_running_one(client, analysis_configured):
    """The escape from "already running for every table": pending jobs are
    failed as cancelled, the recording stops pretending to analyse, and a job
    mid-request is left to finish (≤ its HTTP timeout) and reported."""
    from citizens.services.jobs import has_live_job

    with session_scope() as session:
        ids = _seed(session)
        recording = session.get(Recording, ids["recording"])
        recording.state = "ANALYZING"
        waiting = enqueue_job(session, "ANALYZE_TABLE", {"recording_id": ids["recording"]})
        waiting.state = "RETRY"
        waiting.next_attempt_at = _future(200)
        running = enqueue_job(session, "ANALYZE_ROUND", {"round_id": ids["round"], "revision": 1})
        running.state = "RUNNING"
        waiting_id, running_id = waiting.id, running.id

    response = client.post(f"/api/v1/rounds/{ids['round']}/analysis/cancel")
    assert response.status_code == 200, response.text
    assert response.json() == {"cancelled": 1, "running": 1}

    with session_scope() as session:
        assert session.get(AppJob, waiting_id).state == "FAILED"
        assert session.get(AppJob, waiting_id).last_error == "cancelled by organizer"
        assert session.get(AppJob, running_id).state == "RUNNING"
        recording = session.get(Recording, ids["recording"])
        assert recording.state == "ANALYSIS_FAILED"
        assert not has_live_job(session, "ANALYZE_TABLE", "recording_id", ids["recording"])
    body = client.get(f"/api/v1/rounds/{ids['round']}/findings").json()
    assert body["tables"][0]["recording"]["job"]["failure_reason"] == "CANCELLED"


def test_recluster_waits_for_pending_tables_then_queues_exactly_once(client, analysis_configured):
    with session_scope() as session:
        ids = _seed(session)
        session.get(Recording, ids["recording"]).state = "TRANSCRIBING"
    blocked = client.post(f"/api/v1/rounds/{ids['round']}/recluster")
    assert blocked.status_code == 409, blocked.text
    with session_scope() as session:
        session.get(Recording, ids["recording"]).state = "READY_FOR_REVIEW"
    first = client.post(f"/api/v1/rounds/{ids['round']}/recluster")
    assert first.status_code == 202 and first.json() == {"queued": True}
    second = client.post(f"/api/v1/rounds/{ids['round']}/recluster")
    assert second.status_code == 202 and second.json() == {"queued": False}
    with session_scope() as session:
        assert len(_live(session, ids["round"])) == 1


def test_files_listing_and_live_tab_carry_the_job_behind_a_failed_table(client):
    from citizens.services import rounds as rounds_svc

    with session_scope() as session:
        ids = _seed(session)
        recording = session.get(Recording, ids["recording"])
        recording.state = "TRANSCRIPTION_FAILED"
        recording.error_code = "RATE_LIMITED"
        job = enqueue_job(session, "TRANSCRIBE_FINAL", {"recording_id": ids["recording"]}, max_attempts=8)
        job.state = "RETRY"
        job.attempts = 3
        job.next_attempt_at = _future(120)
        job.last_error = "Mistral returned HTTP 429 (rate limited): Too many requests"
    body = client.get(f"/api/v1/assemblies/{ids['assembly']}/files").json()
    entries = [t for r in body["rounds"] for t in r["tables"]]
    entry = next(e for e in entries if e["recording_id"] == ids["recording"])
    assert entry["error_code"] == "RATE_LIMITED"
    assert entry["job"]["state"] == "RETRY" and entry["job"]["max_attempts"] == 8
    assert entry["job"]["failure_reason"] == "PROVIDER_RATE_LIMIT"
    with session_scope() as session:
        monitor = rounds_svc.round_monitor(session, session.get(Round, ids["round"]))
    assert monitor["tables"][0]["recording"]["job"]["failure_reason"] == "PROVIDER_RATE_LIMIT"
