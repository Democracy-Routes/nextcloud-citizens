# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Why did the last job for this recording or round fail?

The job runner keeps the provider's words in `AppJob.last_error`, and until
now nothing read them back: the organizer saw "The AI analysis did not
complete" while the row said "authentication failed (403)". At the
2026-09-18 rehearsal that cost five blind re-runs against a rejected key and
eight minutes staring at "already running" while a 429 backed off.

`classify` maps the free text onto a small stable set of reasons the UI can
explain in the organizer's language; `latest_jobs` finds the newest job per
recording or round in one scan, so a listing does not pay a query per row.
"""

import json
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import AppJob

#: every value `classify` can return — the UI must have a sentence for each
FAILURE_REASONS = (
    "PROVIDER_AUTH", "PROVIDER_RATE_LIMIT", "PROVIDER_TIMEOUT", "PROVIDER_HTTP",
    "SCHEMA_INVALID", "NOT_CONFIGURED", "NO_TRANSCRIPT", "AUDIO_MISSING",
    "CANCELLED", "UNKNOWN",
)

#: "No Mistral API key configured", "No Whisper endpoint configured",
#: "No Vosk server URL configured" — the provider name sits in the middle
_NOT_CONFIGURED = re.compile(r"\bno (?:\w+ )*(?:api key|endpoint|server url)\b")

#: how many recent jobs of a type to scan for the newest per id; a listing
#: only ever cares about the last few attempts per recording
SCAN_LIMIT = 500


def classify(last_error: str) -> str:
    text = (last_error or "").strip().lower()
    if not text:
        return "UNKNOWN"
    if "cancelled by organizer" in text:
        return "CANCELLED"
    if "authentication failed" in text or "(401)" in text or "(403)" in text:
        return "PROVIDER_AUTH"
    if "429" in text or "rate limit" in text:
        return "PROVIDER_RATE_LIMIT"
    if "timeout" in text or "timed out" in text:
        return "PROVIDER_TIMEOUT"
    if _NOT_CONFIGURED.search(text) or "not configured" in text:
        return "NOT_CONFIGURED"
    if "failed validation" in text or "unexpected payload" in text or "non-json" in text:
        return "SCHEMA_INVALID"
    if "no transcript" in text or "never wrote a transcript" in text \
            or "produced no text" in text or "captions unreadable" in text:
        return "NO_TRANSCRIPT"
    if "audio file is missing" in text or "audio has been deleted" in text \
            or "canonical audio" in text or "empty pcm" in text:
        return "AUDIO_MISSING"
    if "http" in text or "request failed" in text or "unreachable" in text \
            or "rejected" in text or "streaming failed" in text:
        return "PROVIDER_HTTP"
    return "UNKNOWN"


def describe(job: AppJob) -> dict:
    """The shape every payload carries beside `error_code`."""
    return {
        "state": job.state,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "next_attempt_at": _iso(job.next_attempt_at) if job.state == "RETRY" else None,
        "failure_reason": classify(job.last_error) if job.last_error else None,
        "failure_detail": (job.last_error or "")[:300] or None,
    }


def latest_jobs(
    session: Session, job_type: str, payload_key: str, values: set[str] | None = None
) -> dict[str, AppJob]:
    """The newest job of `job_type` per id, for the ids in `values` (all if None).

    The payload is JSON, so this filters in Python like `has_live_job`; the
    scan is newest-first and stops once every wanted id has been seen.
    """
    wanted = set(values) if values is not None else None
    if wanted is not None and not wanted:
        return {}
    rows = session.execute(
        select(AppJob)
        .where(AppJob.type == job_type)
        .order_by(AppJob.created_at.desc())
        .limit(SCAN_LIMIT)
    ).scalars()
    found: dict[str, AppJob] = {}
    for job in rows:
        try:
            key = json.loads(job.payload_json).get(payload_key)
        except (TypeError, ValueError):
            continue
        if not key or key in found or (wanted is not None and key not in wanted):
            continue
        found[key] = job
        if wanted is not None and len(found) == len(wanted):
            break
    return found


#: which job a recording's state is waiting on or failed in
JOB_TYPE_FOR_STATE = {
    "ASSEMBLING": "ASSEMBLE_AUDIO", "AUDIO_INVALID": "ASSEMBLE_AUDIO",
    "TRANSCRIBING": "TRANSCRIBE_FINAL", "TRANSCRIPTION_FAILED": "TRANSCRIBE_FINAL",
    "ANALYZING": "ANALYZE_TABLE", "ANALYSIS_FAILED": "ANALYZE_TABLE",
}


def jobs_for_recordings(session: Session, recordings) -> dict[str, dict | None]:
    """{recording_id: describe(newest job)} for the job its state points at.

    One scan per job type, not one query per row: the Files tab lists every
    recording of the assembly and the Live tab polls every few seconds.
    """
    wanted: dict[str, set[str]] = {}
    for recording in recordings:
        job_type = JOB_TYPE_FOR_STATE.get(recording.state)
        if job_type:
            wanted.setdefault(job_type, set()).add(recording.id)
    found: dict[str, dict] = {}
    for job_type, ids in wanted.items():
        for recording_id, job in latest_jobs(session, job_type, "recording_id", ids).items():
            found[recording_id] = describe(job)
    return {recording.id: found.get(recording.id) for recording in recordings}


def latest_job_failure(session: Session, job_type: str, payload_key: str, value: str) -> dict | None:
    job = latest_jobs(session, job_type, payload_key, {value}).get(value)
    return describe(job) if job is not None else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
