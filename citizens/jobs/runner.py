# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Durable job runner (brief §49).

Jobs live in SQLite; the runner polls for due work, executes handlers in
worker threads (they use sync SQLAlchemy + subprocesses) — up to
`citizens_job_workers` at once — and applies exponential backoff on failure.
On startup, stale RUNNING jobs (from a crash or restart) are recovered to
RETRY. Claiming marks a job RUNNING inside its own write transaction, so two
workers of the same process can never take the same job.

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

from citizens.config import get_settings
from citizens.db.models import AppJob
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.jobs.handlers import HANDLERS, CapacityBusyError, PermanentJobError
from citizens.jobs.sweep import SWEEP_INTERVAL_SECONDS, run_sweeps
from citizens.logging_setup import get_logger

log = get_logger(__name__)

POLL_INTERVAL_SECONDS = 3.0
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 3600
# How soon to look again when a job is merely waiting for a transcription
# slot (CapacityBusyError). Fixed rather than exponential: the wait is not a
# failure, and live caption sessions free their slots on a minutes scale.
CAPACITY_RETRY_SECONDS = 60
# How long a RUNNING job may hold its lease before another pass reclaims it.
# Generous, because a long transcription legitimately takes many minutes.
# Safe because one run_forever loop (one container) does all the claiming,
# each claim in its own write transaction; reclaiming would double-run jobs
# only if a second process ever ran the loop against the same database.
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
        except CapacityBusyError as exc:
            # not a failure: every transcription slot is taken (usually by
            # live captions during an event). Look again shortly, and give
            # the attempt back — waiting for a busy hour to pass must never
            # march a good job to FAILED.
            session.rollback()
            job = session.get(AppJob, job_id)
            job.attempts = max(0, job.attempts - 1)
            job.state = "RETRY"
            job.locked_at = None
            job.last_error = str(exc)[:2000]
            job.next_attempt_at = utcnow() + timedelta(seconds=CAPACITY_RETRY_SECONDS)
            log.info("job_waiting_for_capacity", job_id=job.id, job_type=job.type)
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
                # a provider that says how long to wait (429 Retry-After)
                # knows better than the exponential guess — still bounded
                retry_after = getattr(exc, "retry_after", None)
                if retry_after:
                    delay = min(max(delay, retry_after), BACKOFF_MAX_SECONDS)
                job.next_attempt_at = utcnow() + timedelta(seconds=delay)
                log.warning(
                    "job_retry_scheduled", job_id=job.id, job_type=job.type, delay_seconds=delay,
                    exc_info=True,
                )
        else:
            job.state = "SUCCEEDED"
            job.locked_at = None
            log.info("job_succeeded", job_id=job.id, job_type=job.type)


def _worker_count(workers: int | None) -> int:
    if workers is None:
        workers = get_settings().citizens_job_workers
    return max(1, int(workers))


async def run_forever(stop_event: asyncio.Event, workers: int | None = None) -> None:
    """Claim due jobs and run each in its own thread, up to `workers` at once.

    Ten tables end a round together. One worker handled their assembly,
    transcription and analysis strictly in sequence, which put the report
    35-85 minutes past the end of a 40-minute round; with a pool the wait is
    about one table's worth. Throttling towards the providers is not done
    here: the transcription handler already honours the per-provider caps in
    Settings (a job that finds every slot taken steps back for a minute
    without losing an attempt), and a rate-limited analysis waits out the
    provider's Retry-After.
    """
    recover_stale_jobs()
    pool_size = _worker_count(workers)
    log.info("job_runner_started", workers=pool_size)
    running: set[asyncio.Task] = set()
    stopping = asyncio.create_task(stop_event.wait())
    last_sweep = 0.0
    try:
        while not stop_event.is_set():
            # before claiming work, not after: a steady stream of jobs would
            # otherwise `continue` past the sweep forever
            now = time.monotonic()
            if now - last_sweep >= SWEEP_INTERVAL_SECONDS:
                last_sweep = now
                await asyncio.to_thread(run_sweeps)
            running = {task for task in running if not task.done()}
            try:
                while len(running) < pool_size:
                    job_id = await asyncio.to_thread(_claim_next_job)
                    if job_id is None:
                        break
                    running.add(asyncio.create_task(asyncio.to_thread(_run_job, job_id)))
            except Exception:
                log.error("job_runner_iteration_failed", exc_info=True)
            # Wake when a job finishes (its follow-up may already be due),
            # when told to stop, or after the poll interval — whichever first.
            await asyncio.wait(
                {stopping, *running}, timeout=POLL_INTERVAL_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
    finally:
        stopping.cancel()
        # let the jobs in flight record their result; each is bounded by its
        # own HTTP timeout, and a job cut off anyway is reclaimed by the lease
        if running:
            await asyncio.wait(running)
