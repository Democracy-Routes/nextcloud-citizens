# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A job must never be stranded in RUNNING.

_run_job set the job to SUCCEEDED inside its session_scope. If THAT commit
failed — a full disk is a modeled condition on these paths — the exception
escaped to run_forever, which logs and swallows it. The row stayed RUNNING with
locked_at set, and the claim query only ever looked at QUEUED and RETRY, so the
job never ran again until somebody restarted the container.

The worst pairing was with audio assembly: the chunk files had already been
unlinked, the rollback restored the rows that pointed at them, and every later
attempt then failed permanently.
"""

from datetime import timedelta

from citizens.db.models import AppJob
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.jobs import runner
from citizens.services.jobs import enqueue_job


def _job(job_type="ASSEMBLE_AUDIO", payload=None, state="QUEUED", **kwargs):
    with session_scope() as session:
        job = enqueue_job(session, job_type, payload or {"recording_id": "rec-1"})
        job.state = state
        for key, value in kwargs.items():
            setattr(job, key, value)
        return job.id


def _reload(job_id):
    with session_scope() as session:
        job = session.get(AppJob, job_id)
        return {
            "state": job.state,
            "locked_at": job.locked_at,
            "attempts": job.attempts,
            "last_error": job.last_error,
        }


def test_a_job_whose_bookkeeping_fails_is_rescheduled_not_wedged(database, monkeypatch):
    # exactly what _claim_next_job leaves behind before _run_job is called
    job_id = _job(state="RUNNING", locked_at=utcnow(), attempts=1)

    def explode(_job_id):
        raise OSError("[Errno 28] No space left on device")

    monkeypatch.setattr(runner, "_run_job_inner", explode)
    runner._run_job(job_id)

    after = _reload(job_id)
    assert after["state"] in ("RETRY", "FAILED"), (
        f"the job is {after['state']} — it will never be claimed again, because "
        "the claim query does not look at RUNNING rows"
    )
    assert after["locked_at"] is None


def test_a_job_out_of_attempts_whose_bookkeeping_fails_is_failed(database, monkeypatch):
    job_id = _job(state="RUNNING")
    with session_scope() as session:
        job = session.get(AppJob, job_id)
        job.attempts = job.max_attempts

    monkeypatch.setattr(
        runner, "_run_job_inner", lambda _id: (_ for _ in ()).throw(OSError("disk"))
    )
    runner._run_job(job_id)

    assert _reload(job_id)["state"] == "FAILED"


def test_a_running_job_past_its_lease_is_reclaimed(database):
    """The backstop for anything that leaves a job RUNNING, including a
    container killed between the handler finishing and its commit."""
    job_id = _job(
        state="RUNNING",
        locked_at=utcnow() - timedelta(seconds=runner.RUNNING_LEASE_SECONDS + 60),
    )

    claimed = runner._claim_next_job()

    assert claimed == job_id, "a job stuck in RUNNING was never picked up again"
    assert _reload(job_id)["state"] == "RUNNING"


def test_a_running_job_inside_its_lease_is_left_alone(database):
    """Reclaiming too early would double-run work that is merely slow."""
    _job(state="RUNNING", locked_at=utcnow() - timedelta(seconds=30))

    assert runner._claim_next_job() is None


def test_a_reclaimed_job_counts_another_attempt(database):
    """Otherwise a job that wedges the worker every time retries forever."""
    job_id = _job(
        state="RUNNING",
        locked_at=utcnow() - timedelta(seconds=runner.RUNNING_LEASE_SECONDS + 60),
        attempts=2,
    )

    runner._claim_next_job()

    assert _reload(job_id)["attempts"] == 3


def test_a_normal_queued_job_is_still_claimed(database):
    job_id = _job()
    assert runner._claim_next_job() == job_id


def test_chunks_are_reclaimed_only_after_the_new_state_is_committed(database):
    """assemble_recording must hand the chunks back rather than deleting them,
    so a failed commit cannot leave rows rolled back with their files gone."""
    import inspect

    from citizens.services import audio

    source = inspect.getsource(audio.assemble_recording)
    assert "_discard_chunks(" not in source, (
        "assemble_recording still reclaims chunks itself — if the commit that "
        "records AUDIO_READY fails, the rows come back but the files do not"
    )

    handler_source = inspect.getsource(
        __import__("citizens.jobs.handlers", fromlist=["x"]).handle_assemble_audio
    )
    assert handler_source.index("session.commit()") < handler_source.index("reclaim_chunks(")


def test_no_other_caller_relies_on_assemble_reclaiming_chunks():
    """Moving the reclaim would silently stop cleaning up if something else
    called assemble_recording."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "citizens"
    callers = [
        path.name
        for path in root.rglob("*.py")
        if "assemble_recording(" in path.read_text() and path.name != "audio.py"
    ]
    assert callers == ["handlers.py"], f"unexpected callers: {callers}"
