# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Jobs run side by side, and the pool degrades to the old sequential runner.

Ten tables end a round together; one worker processed their transcriptions
and analyses in strict sequence, so the report was 35-85 minutes away. The
pool runs up to `workers` jobs at once. What must not change: every claim is
exclusive, a failing job takes nobody else down, a job waiting for a
provider slot steps back without losing an attempt, and stopping lets the
jobs in flight finish.
"""

import asyncio
import threading
import time

from sqlalchemy import select

from citizens.db.models import AppJob
from citizens.db.session import session_scope
from citizens.jobs import runner
from citizens.jobs.handlers import CapacityBusyError
from citizens.services.jobs import enqueue_job

SLEEP = 0.3


def _states(job_type):
    with session_scope() as session:
        return sorted(
            (job.state, job.attempts)
            for job in session.scalars(select(AppJob).where(AppJob.type == job_type))
        )


def _drive(workers, done, timeout=10.0):
    """Run the loop until `done()` says so (or the deadline), then stop it."""

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(runner.run_forever(stop, workers=workers))
        deadline = time.monotonic() + timeout
        while not done() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        stop.set()
        await task

    asyncio.run(scenario())


def _quiet(monkeypatch):
    monkeypatch.setattr(runner, "POLL_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(runner, "run_sweeps", lambda: None)


def test_ten_jobs_run_at_once_and_one_worker_runs_them_in_sequence(database, monkeypatch):
    _quiet(monkeypatch)
    spans = []
    lock = threading.Lock()

    def sleeper(session, payload):
        # the runner's contract: commit before the long call, or the write
        # lock is held for the whole job and every other worker waits behind it
        session.commit()
        started = time.monotonic()
        time.sleep(SLEEP)
        with lock:
            spans.append((started, time.monotonic()))

    monkeypatch.setitem(runner.HANDLERS, "TEST_SLEEP", sleeper)
    with session_scope() as session:
        for n in range(10):
            enqueue_job(session, "TEST_SLEEP", {"n": n})

    began = time.monotonic()
    _drive(10, lambda: len(spans) == 10)
    elapsed = time.monotonic() - began
    assert _states("TEST_SLEEP") == [("SUCCEEDED", 1)] * 10
    assert elapsed < SLEEP * 4, f"ten jobs took {elapsed:.2f}s — they did not overlap"
    overlapping = max(sum(1 for s, e in spans if s <= t < e) for t, _ in spans)
    assert overlapping >= 5, f"at most {overlapping} jobs ran together"

    spans.clear()
    with session_scope() as session:
        for n in range(4):
            enqueue_job(session, "TEST_SLEEP", {"n": n})
    began = time.monotonic()
    _drive(1, lambda: len(spans) == 4)
    assert time.monotonic() - began >= SLEEP * 4 * 0.9
    for (_, end_a), (start_b, _) in zip(sorted(spans), sorted(spans)[1:], strict=False):
        assert start_b >= end_a - 0.01, "workers=1 must not overlap jobs"


def test_a_failing_job_takes_nobody_else_down(database, monkeypatch):
    _quiet(monkeypatch)
    finished = []

    def handler(session, payload):
        if payload.get("explode"):
            raise RuntimeError("provider melted")
        session.commit()
        time.sleep(0.05)
        finished.append(payload["n"])

    monkeypatch.setitem(runner.HANDLERS, "TEST_MIXED", handler)
    with session_scope() as session:
        enqueue_job(session, "TEST_MIXED", {"n": 0, "explode": True})
        for n in range(1, 4):
            enqueue_job(session, "TEST_MIXED", {"n": n})

    _drive(4, lambda: len(finished) == 3 and ("RETRY", 1) in _states("TEST_MIXED"))
    states = _states("TEST_MIXED")
    assert states.count(("SUCCEEDED", 1)) == 3
    assert ("RETRY", 1) in states, states


def test_a_job_waiting_for_a_provider_slot_steps_back_without_losing_an_attempt(database, monkeypatch):
    _quiet(monkeypatch)
    ran = []

    def handler(session, payload):
        if payload.get("busy"):
            raise CapacityBusyError("mistral is at its batch concurrency cap")
        ran.append(payload["n"])

    monkeypatch.setitem(runner.HANDLERS, "TEST_CAP", handler)
    with session_scope() as session:
        enqueue_job(session, "TEST_CAP", {"n": 0, "busy": True})
        enqueue_job(session, "TEST_CAP", {"n": 1})
        enqueue_job(session, "TEST_CAP", {"n": 2})

    _drive(3, lambda: len(ran) == 2 and ("RETRY", 0) in _states("TEST_CAP"))
    states = _states("TEST_CAP")
    assert ("RETRY", 0) in states, "the attempt must be given back while waiting for a slot"
    assert states.count(("SUCCEEDED", 1)) == 2


def test_stopping_lets_the_jobs_in_flight_finish(database, monkeypatch):
    _quiet(monkeypatch)
    started = threading.Event()
    finished = []

    def slow(session, payload):
        session.commit()
        started.set()
        time.sleep(0.4)
        finished.append(True)

    monkeypatch.setitem(runner.HANDLERS, "TEST_SLOW", slow)
    with session_scope() as session:
        enqueue_job(session, "TEST_SLOW", {})

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(runner.run_forever(stop, workers=3))
        while not started.is_set():
            await asyncio.sleep(0.02)
        stop.set()
        await task  # returns only once the running job has recorded its result

    asyncio.run(scenario())
    assert finished == [True]
    assert _states("TEST_SLOW") == [("SUCCEEDED", 1)]


def test_the_pool_size_comes_from_settings_and_never_drops_below_one(monkeypatch):
    from citizens.config import get_settings

    monkeypatch.setenv("CITIZENS_JOB_WORKERS", "0")
    get_settings.cache_clear()
    try:
        assert runner._worker_count(None) == 1
        assert runner._worker_count(7) == 7
    finally:
        get_settings.cache_clear()
