# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Enqueueing durable jobs (runner lives in citizens/jobs/)."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import AppJob

#: job states that mean "this work is still going to happen"
LIVE_JOB_STATES = ("QUEUED", "RUNNING", "RETRY")


def enqueue_job(session: Session, job_type: str, payload: dict, max_attempts: int = 5) -> AppJob:
    job = AppJob(type=job_type, payload_json=json.dumps(payload), max_attempts=max_attempts)
    session.add(job)
    session.flush()
    return job


def has_live_job(session: Session, job_type: str, payload_key: str, value: str) -> bool:
    """Is a job of this type still queued, running or backing off for this id?

    The payload is JSON, so this filters in Python rather than matching the
    serialized string: two payloads with the same meaning can differ in key
    order or in fields the caller did not set.

    Callers use it to avoid acting on something a job is in the middle of —
    abandoning a recording that is being assembled, or deleting the audio out
    from under it.
    """
    payloads = session.execute(
        select(AppJob.payload_json).where(
            AppJob.type == job_type, AppJob.state.in_(LIVE_JOB_STATES)
        )
    ).scalars()
    for raw in payloads:
        try:
            if json.loads(raw).get(payload_key) == value:
                return True
        except (TypeError, ValueError):
            continue
    return False
