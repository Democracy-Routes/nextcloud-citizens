# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""When does cross-table clustering need to run again?

Two counters on the round answer it. `analysis_input_revision` bumps whenever
the findings the clustering reads change: a table (re)analysed, a table
dropped from the round, an organizer rejecting or editing a finding.
`analysis_applied_revision` is set from the input revision a run STARTED from,
once it succeeds. The round is stale exactly when input > applied.

A review landing while a run is in flight cannot be seen by that run, so one
follow-up may queue behind a RUNNING job; further changes coalesce into it —
it reads the newest inputs when it starts. A QUEUED job likewise absorbs every
change until it starts.

Plain approval does not bump anything: the clustering reads every finding that
is not REJECTED, so approving a draft changes nothing it would see — re-running
would only spend a model call to arrive at the same clusters.
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import AppJob, Recording, Round
from citizens.logging_setup import get_logger
from citizens.services.jobs import LIVE_JOB_STATES, enqueue_job

log = get_logger(__name__)

#: recordings in these states still owe the round their table findings
_HEALTHY_PENDING = frozenset({
    "CREATED", "RECORDING", "FINALIZING", "WAITING_FOR_CHUNKS", "ASSEMBLING",
    "AUDIO_READY", "TRANSCRIBING", "TRANSCRIBED", "ANALYZING",
})


def bump_round_inputs(session: Session, round_id: str) -> Round | None:
    """The clustering's inputs changed; the next run must see them."""
    round_ = session.get(Round, round_id)
    if round_ is None:
        return None
    round_.analysis_input_revision += 1
    session.flush()
    return round_


def _live_round_jobs(session: Session, round_id: str) -> list[AppJob]:
    # the payload is JSON and now carries a revision, so match by parsing it
    # rather than by serialized-string equality (see services/jobs.has_live_job)
    jobs = session.execute(
        select(AppJob).where(AppJob.type == "ANALYZE_ROUND", AppJob.state.in_(LIVE_JOB_STATES))
    ).scalars()
    matching = []
    for job in jobs:
        try:
            if json.loads(job.payload_json).get("round_id") == round_id:
                matching.append(job)
        except (TypeError, ValueError):
            continue
    return matching


def _revision_of(job: AppJob) -> int:
    try:
        return int(json.loads(job.payload_json).get("revision", 0))
    except (TypeError, ValueError):
        return 0


def tables_pending(session: Session, round_id: str) -> bool:
    states = session.execute(
        select(Recording.state).where(
            Recording.round_id == round_id,
            Recording.transcript_deleted_at.is_(None),
        )
    ).scalars()
    return any(state in _HEALTHY_PENDING for state in states)


def enqueue_round_analysis_if_stale(session: Session, round_id: str) -> bool:
    """Queue a clustering run unless one already covers the current inputs.

    Returns whether a job was queued. A round with tables still owing their
    findings is left alone: whichever completion arrives last re-enters here
    with a higher revision and queues the run that sees everything.
    """
    round_ = session.get(Round, round_id)
    if round_ is None or tables_pending(session, round_id):
        return False
    live = _live_round_jobs(session, round_id)
    if any(job.state in ("QUEUED", "RETRY") for job in live):
        return False  # it reads the newest inputs when it starts; this change coalesces
    running = [job for job in live if job.state == "RUNNING"]
    if running:
        # the run in flight started from a revision it stamped on itself
        # (record_run_started); anything newer it cannot have seen
        if round_.analysis_input_revision <= max(_revision_of(job) for job in running):
            return False
    elif round_.analysis_input_revision <= round_.analysis_applied_revision:
        return False
    enqueue_job(
        session, "ANALYZE_ROUND",
        {"round_id": round_id, "revision": round_.analysis_input_revision},
    )
    log.info(
        "round_analysis_enqueued",
        round_id=round_id,
        revision=round_.analysis_input_revision,
        follow_up=bool(running),
    )
    return True


def record_run_started(session: Session, round_id: str) -> int:
    """At the start of a run: capture the input revision, and stamp it on the
    running job so a change landing later can tell the run never saw it."""
    round_ = session.get(Round, round_id)
    captured = round_.analysis_input_revision if round_ is not None else 0
    for job in _live_round_jobs(session, round_id):
        if job.state == "RUNNING":
            job.payload_json = json.dumps({"round_id": round_id, "revision": captured})
    session.flush()
    return captured


def record_run_applied(session: Session, round_id: str, captured: int) -> None:
    """After a successful run: the clusters now reflect `captured`."""
    round_ = session.get(Round, round_id)
    if round_ is not None and captured > round_.analysis_applied_revision:
        round_.analysis_applied_revision = captured
        session.flush()
