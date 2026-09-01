# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Durable single-worker job runner (brief §49).

Jobs live in SQLite; the runner polls for due work, executes handlers in a
worker thread (they use sync SQLAlchemy + subprocesses), and applies
exponential backoff on failure. On startup, stale RUNNING jobs (from a crash
or restart) are recovered to RETRY.

CONTRACT: handlers run inside ONE session whose transaction takes SQLite's
single write lock (BEGIN IMMEDIATE). Handlers MUST session.commit() right
before any long external call (ffmpeg, STT/LLM HTTP) — a transaction held
across those starves every API request into 500s after busy_timeout.
"""

import asyncio
import json
import time
from datetime import timedelta

from sqlalchemy import and_, or_, select

from citizens.db.models import AppJob
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.jobs.handlers import HANDLERS, PermanentJobError
from citizens.jobs.sweep import SWEEP_INTERVAL_SECONDS, run_sweeps
from citizens.logging_setup import get_logger

log = get_logger(__name__)

POLL_INTERVAL_SECONDS = 3.0
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 3600
# How long a RUNNING job may hold its lease before another pass reclaims it.
# Generous, because a long transcription legitimately takes many minutes.
# Safe because exactly one worker runs (a single container, one run_forever
# task); reclaiming would double-run jobs if that ever stopped being true.
RUNNING_LEASE_SECONDS = 1800


def recover_stale_jobs() -> int:
    with session_scope() as session:
        stale = list(
            session.execute(select(AppJob).where(AppJob.state == "RUNNING")).scalars()
        )
        for job in stale:
            job.state = "RETRY"
            job.locked_at = None
            job.next_attempt_at = utcnow()
        if stale:
            log.warning("jobs_recovered_after_restart", count=len(stale))
        return len(stale)


def _claim_next_job() -> str | None:
    with session_scope() as session:
        now = utcnow()
        lease_expiry = now - timedelta(seconds=RUNNING_LEASE_SECONDS)
        job = session.execute(
            select(AppJob)
            .where(
                or_(
                    and_(
                        AppJob.state.in_(("QUEUED", "RETRY")),
                        AppJob.next_attempt_at <= now,
                    ),
                    # A job left RUNNING past its lease. recover_stale_jobs
                    # only runs at startup, so without this a job whose final
                    # commit failed stayed RUNNING — invisible to the claim
                    # query — until somebody restarted the container.
                    and_(
                        AppJob.state == "RUNNING",
                        AppJob.locked_at.is_not(None),
                        AppJob.locked_at < lease_expiry,
                    ),
                )
            )
            .order_by(AppJob.next_attempt_at)
            .limit(1)
        ).scalar_one_or_none()
        if job is None:
            return None
        if job.state == "RUNNING":
            log.warning(
                "job_lease_expired", job_id=job.id, job_type=job.type, attempts=job.attempts
            )
        job.state = "RUNNING"
        job.locked_at = utcnow()
        job.attempts = job.attempts + 1
        return job.id


def _run_job(job_id: str) -> None:
    try:
        _run_job_inner(job_id)
    except Exception:
        # The bookkeeping commit itself failed (a full disk is a modeled
        # condition on these paths). run_forever swallows this, so without a
        # second attempt in a fresh session the row stays RUNNING with
        # locked_at set — and the claim query never looks at RUNNING rows, so
        # the job would never run again until a restart.
        log.error("job_bookkeeping_failed", job_id=job_id, exc_info=True)
        _release_job_after_failure(job_id)


def _release_job_after_failure(job_id: str) -> None:
    try:
        with session_scope() as session:
            job = session.get(AppJob, job_id)
            if job is None or job.state != "RUNNING":
                return
            job.locked_at = None
            job.last_error = "The job could not record its own result"[:2000]
            if job.attempts >= job.max_attempts:
                job.state = "FAILED"
            else:
                job.state = "RETRY"
                delay = min(BACKOFF_BASE_SECONDS * (2 ** (job.attempts - 1)), BACKOFF_MAX_SECONDS)
                job.next_attempt_at = utcnow() + timedelta(seconds=delay)
    except Exception:
        # nothing more we can do here; the lease reclaim in _claim_next_job is
        # the backstop
        log.error("job_release_failed", job_id=job_id, exc_info=True)


def _run_job_inner(job_id: str) -> None:
    with session_scope() as session:
        job = session.get(AppJob, job_id)
        if job is None:
            return
        handler = HANDLERS.get(job.type)
        log.info("job_started", job_id=job.id, job_type=job.type, attempt=job.attempts)
        try:
            if handler is None:
                raise PermanentJobError(f"No handler for job type {job.type}")
            handler(session, json.loads(job.payload_json))
        except PermanentJobError as exc:
            job.state = "FAILED"
            job.last_error = str(exc)[:2000]
            job.locked_at = None
            log.error("job_failed_permanently", job_id=job.id, job_type=job.type)
        except Exception as exc:
            session.rollback()
            job = session.get(AppJob, job_id)
            job.last_error = str(exc)[:2000]
            job.locked_at = None
            if job.attempts >= job.max_attempts:
                job.state = "FAILED"
                log.error(
                    "job_failed_max_attempts", job_id=job.id, job_type=job.type, attempts=job.attempts
                )
            else:
                job.state = "RETRY"
                delay = min(BACKOFF_BASE_SECONDS * (2 ** (job.attempts - 1)), BACKOFF_MAX_SECONDS)
                job.next_attempt_at = utcnow() + timedelta(seconds=delay)
                log.warning(
                    "job_retry_scheduled", job_id=job.id, job_type=job.type, delay_seconds=delay,
                    exc_info=True,
                )
        else:
            job.state = "SUCCEEDED"
            job.locked_at = None
            log.info("job_succeeded", job_id=job.id, job_type=job.type)


async def run_forever(stop_event: asyncio.Event) -> None:
    recover_stale_jobs()
    last_sweep = 0.0
    while not stop_event.is_set():
        # before claiming work, not after: a steady stream of jobs would
        # otherwise `continue` past the sweep forever
        now = time.monotonic()
        if now - last_sweep >= SWEEP_INTERVAL_SECONDS:
            last_sweep = now
            await asyncio.to_thread(run_sweeps)
        try:
            job_id = await asyncio.to_thread(_claim_next_job)
            if job_id is not None:
                await asyncio.to_thread(_run_job, job_id)
                continue  # look for more work immediately
        except Exception:
            log.error("job_runner_iteration_failed", exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
        except TimeoutError:
            pass
