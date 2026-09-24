# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organizer API: AI findings review (approve/reject/edit) and analysis triggers."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from citizens.db.models import AppJob, Finding, Recording, TranscriptSegment
from citizens.db.models.base import utcnow
from citizens.db.session import get_db
from citizens.security.identity import CurrentUser
from citizens.services import job_failures, provider_config
from citizens.services.analysis import analysis_ready
from citizens.services.assemblies import get_owned_round
from citizens.services.audit import record_audit_event
from citizens.services.jobs import LIVE_JOB_STATES, enqueue_job
from citizens.services.recording_states import transition
from citizens.services.report import _cross_table_evidence
from citizens.services.round_analysis import (
    bump_round_inputs,
    enqueue_round_analysis_if_stale,
    tables_pending,
)
from citizens.services.speaking import round_speaking_balance

router = APIRouter()

DB = Annotated[Session, Depends(get_db)]


def _finding_payload(session: Session, finding: Finding, table_numbers: dict[str, int]) -> dict:
    evidence = []
    if finding.evidence:
        segment_ids = [e.transcript_segment_id for e in finding.evidence]
        segments = session.execute(
            select(TranscriptSegment).where(TranscriptSegment.id.in_(segment_ids))
        ).scalars()
        evidence = [
            {
                "segment_id": segment.id,
                "speaker": segment.speaker_label,
                "start": segment.start_seconds,
                "end": segment.end_seconds,
                "text": segment.text,
            }
            for segment in sorted(segments, key=lambda s: s.start_seconds)
        ]
    elif finding.scope == "round":
        # a cross-table finding stores no evidence of its own; borrow a sample
        # from the table findings it clustered, labelled per table, so the
        # Analysis tab shows the same verifiable quotes the report does
        evidence = [
            {
                "segment_id": quote["segment_id"],
                "table_number": quote["table_number"],
                "speaker": quote["speaker"],
                "start": quote["start"],
                "end": quote["end"],
                "text": quote["text"],
            }
            for quote in _cross_table_evidence(session, finding, table_numbers)
        ]
    return {
        "id": finding.id,
        "scope": finding.scope,
        "type": finding.type,
        "title": finding.title,
        "summary": finding.summary,
        "support": finding.support,
        "status": finding.status,
        "table_number": table_numbers.get(finding.table_id or ""),
        "mentioned_table_count": finding.mentioned_table_count,
        "ai_model": finding.ai_model,
        "reviewed_by": finding.reviewed_by,
        "evidence": evidence,
    }


@router.get("/rounds/{round_id}/findings")
def round_findings(round_id: str, user: CurrentUser, session: DB):
    round_ = get_owned_round(session, round_id, user)
    table_numbers = {table.id: table.number for table in round_.tables}
    findings = list(
        session.execute(
            select(Finding)
            .where(Finding.round_id == round_.id)
            .options(selectinload(Finding.evidence))
            .order_by(Finding.created_at)
        ).scalars()
    )
    recordings_full = {
        rec.table_number: rec
        for rec in session.execute(
            select(Recording).where(Recording.round_id == round_.id).order_by(Recording.created_at)
        ).scalars()
    }
    jobs = job_failures.jobs_for_recordings(session, list(recordings_full.values()))
    # error_code and the job's reason were missing here — the one tab whose
    # button offers a re-run could not say why the last run failed, or that
    # a retry was already waiting (2026-09-18: five blind re-runs on a 403)
    recordings = {
        number: {
            "id": rec.id, "state": rec.state, "error_code": rec.error_code or "",
            "job": jobs.get(rec.id),
        }
        for number, rec in recordings_full.items()
    }
    tables_payload = []
    for table in round_.tables:
        table_findings = [f for f in findings if f.scope == "table" and f.table_id == table.id]
        recording = recordings_full.get(table.number)
        tables_payload.append(
            {
                "table_number": table.number,
                "recording": recordings.get(table.number),
                "summary": recording.analysis_summary if recording else "",
                "analyzed": bool(
                    recording and recording.state in ("READY_FOR_REVIEW", "REVIEWED")
                ),
                "findings": [_finding_payload(session, f, table_numbers) for f in table_findings],
            }
        )
    total_tables = len({f.table_id for f in findings if f.scope == "table" and f.table_id})
    return {
        "round_id": round_.id,
        "round_status": round_.status,
        "round_summary": round_.analysis_summary,
        "analysis_configured": analysis_ready(provider_config.default_store()),
        "tables_with_findings": total_tables,
        "cross_table": [
            _finding_payload(session, f, table_numbers) for f in findings if f.scope == "round"
        ],
        "speaking_balance": round_speaking_balance(session, round_),
        "tables": tables_payload,
        # the cross-table clustering has no state of its own on the round; a
        # failed one used to leave every table "ready" and nothing else
        "round_job": job_failures.latest_job_failure(session, "ANALYZE_ROUND", "round_id", round_.id),
    }


@router.post("/rounds/{round_id}/analysis/cancel")
def cancel_pending_analysis(round_id: str, user: CurrentUser, session: DB):
    """Stop the analysis jobs that have not started: queued, or waiting out a
    retry. A job already mid-request finishes within its HTTP timeout and
    is reported, not interrupted.

    Without this, "Analysis is already running for every table" was the
    whole story for as long as the backoff lasted — eight minutes at the
    2026-09-18 rehearsal, with the provider answering 429 every time.
    """
    round_ = get_owned_round(session, round_id, user)
    recording_ids = set(
        session.scalars(select(Recording.id).where(Recording.round_id == round_.id))
    )
    cancelled = running = 0
    for job in session.scalars(
        select(AppJob).where(
            AppJob.type.in_(("ANALYZE_TABLE", "ANALYZE_ROUND")),
            AppJob.state.in_(LIVE_JOB_STATES),
        )
    ):
        try:
            payload = json.loads(job.payload_json)
        except ValueError:
            continue
        recording_id = payload.get("recording_id")
        if payload.get("round_id") != round_.id and recording_id not in recording_ids:
            continue
        if job.state == "RUNNING":
            running += 1
            continue
        job.state = "FAILED"
        job.locked_at = None
        job.last_error = "cancelled by organizer"
        cancelled += 1
        recording = session.get(Recording, recording_id) if recording_id else None
        if recording is not None and recording.state == "ANALYZING":
            # otherwise it stays "analyzing" with nothing working on it
            recording.error_code = "ANALYSIS_FAILED"
            transition(recording, "ANALYSIS_FAILED")
    record_audit_event(
        session, "analysis_cancelled", "round", round_.id, actor=user,
        data={"cancelled": cancelled, "running": running},
    )
    return {"cancelled": cancelled, "running": running}


@router.post("/rounds/{round_id}/recluster", status_code=202)
def request_reclustering(round_id: str, user: CurrentUser, session: DB):
    """Run only the cross-table clustering again, from the tables' current
    findings — not the ten table analyses a full re-run costs."""
    round_ = get_owned_round(session, round_id, user)
    if not analysis_ready(provider_config.default_store()):
        raise HTTPException(
            status_code=409,
            detail="AI analysis is not configured — add an analysis API key in Settings",
        )
    if tables_pending(session, round_.id):
        raise HTTPException(
            status_code=409,
            detail="Tables are still being transcribed or analysed; "
                   "the clustering runs by itself when they finish",
        )
    bump_round_inputs(session, round_.id)
    queued = enqueue_round_analysis_if_stale(session, round_.id)
    record_audit_event(
        session, "reclustering_requested", "round", round_.id, actor=user, data={"queued": queued},
    )
    return {"queued": queued}


class FindingUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(APPROVED|REJECTED|DRAFT)$")
    title: str | None = Field(default=None, min_length=3, max_length=300)
    summary: str | None = Field(default=None, min_length=1, max_length=4000)


@router.put("/findings/{finding_id}")
def update_finding(finding_id: str, data: FindingUpdate, user: CurrentUser, session: DB):
    finding = session.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    get_owned_round(session, finding.round_id, user)

    was_rejected = finding.status == "REJECTED"
    edited = False
    if data.title is not None and data.title != finding.title:
        finding.title = data.title
        edited = True
    if data.summary is not None and data.summary != finding.summary:
        finding.summary = data.summary
        edited = True
    if data.status is not None:
        if data.status == "APPROVED":
            finding.status = "EDITED_AND_APPROVED" if edited else "APPROVED"
        else:
            finding.status = data.status
    elif edited and finding.status in ("APPROVED", "EDITED_AND_APPROVED"):
        finding.status = "EDITED_AND_APPROVED"
    finding.reviewed_by = user
    finding.reviewed_at = utcnow()
    session.flush()
    record_audit_event(
        session, "finding_reviewed", "finding", finding.id, actor=user,
        data={"status": finding.status, "edited": edited},
    )
    # The cross-table clusters were built from the findings as they were.
    # Rejecting (or un-rejecting) changes what the clustering reads, and an
    # edit changes the text it reads — so it must run again from the newest
    # inputs. Plain approval changes nothing it would see; see
    # services/round_analysis. Before this, no review of any kind re-clustered:
    # the report's cross-table section went stale silently.
    if edited or (finding.status == "REJECTED") != was_rejected:
        bump_round_inputs(session, finding.round_id)
        enqueue_round_analysis_if_stale(session, finding.round_id)
    return _finding_payload(session, finding, {})


class BulkApproveIn(BaseModel):
    #: Approve only this table's findings; omit for the whole round.
    table_number: int | None = Field(default=None, ge=1)


@router.post("/rounds/{round_id}/findings/approve")
def approve_drafts(round_id: str, data: BulkApproveIn, user: CurrentUser, session: DB):
    """Approve every draft finding in a round, or in one of its tables.

    Reviewing findings one at a time is what an organizer does after an
    assembly, and they said it was tedious enough to want a way to skip review
    entirely. That is the one thing this must not offer: human approval is what
    the report's methodology note asserts. It is a statement about THIS
    generation of findings — a later analysis run replaces the generation,
    approvals included (services/analysis._delete_existing), and the
    organizer confirms that before re-running.

    Only DRAFT findings. A REJECTED one is a decision somebody made, and
    quietly reversing it in a bulk action would be the worst kind of surprise.
    """
    round_ = get_owned_round(session, round_id, user)
    query = select(Finding).where(Finding.round_id == round_.id, Finding.status == "DRAFT")
    if data.table_number is not None:
        table_ids = [t.id for t in round_.tables if t.number == data.table_number]
        if not table_ids:
            raise HTTPException(status_code=404, detail="This round has no table with that number")
        query = query.where(Finding.table_id.in_(table_ids))

    now = utcnow()
    approved = 0
    for finding in session.execute(query).scalars():
        finding.status = "APPROVED"
        finding.reviewed_by = user
        finding.reviewed_at = now
        approved += 1
        # one row per finding, as the single-finding path writes: it is what
        # makes an individual finding's review history reconstructable
        record_audit_event(
            session, "finding_reviewed", "finding", finding.id, actor=user,
            data={"status": "APPROVED", "edited": False, "bulk": True},
        )
    session.flush()
    return {"approved": approved}


class AnalyzeIn(BaseModel):
    force: bool = False


def _recordings_with_live_analysis(session: Session) -> set[str]:
    """Recording ids that already have an ANALYZE_TABLE job queued, running or
    backing off, so a manual re-run doesn't stack a duplicate behind one that
    is merely slow."""
    live = session.execute(
        select(AppJob.payload_json).where(
            AppJob.type == "ANALYZE_TABLE",
            AppJob.state.in_(("QUEUED", "RUNNING", "RETRY")),
        )
    ).scalars()
    busy = set()
    for payload in live:
        try:
            busy.add(json.loads(payload)["recording_id"])
        except (ValueError, KeyError):
            continue
    return busy


@router.post("/rounds/{round_id}/analyze", status_code=202)
def request_analysis(round_id: str, data: AnalyzeIn, user: CurrentUser, session: DB):
    """(Re)run analysis for every transcribed table of the round; cross-table
    clustering follows automatically once all tables finish."""
    round_ = get_owned_round(session, round_id, user)
    if not analysis_ready(provider_config.default_store()):
        raise HTTPException(
            status_code=409,
            detail="AI analysis is not configured — add an analysis API key in Settings",
        )
    recordings = list(
        session.execute(
            select(Recording).where(
                Recording.round_id == round_.id,
                # ANALYZING is included so a recording whose job exhausted its
                # retries can be recovered — without it the only way out of
                # that state was editing the database by hand
                Recording.state.in_(
                    ("TRANSCRIBED", "ANALYSIS_FAILED", "READY_FOR_REVIEW", "ANALYZING")
                ),
            )
        ).scalars()
    )
    if not recordings:
        raise HTTPException(status_code=409, detail="No transcribed recordings to analyze yet")
    busy = _recordings_with_live_analysis(session)
    queued = 0
    for recording in recordings:
        if recording.id in busy:
            continue  # a job is still working or backing off; don't stack another
        enqueue_job(session, "ANALYZE_TABLE", {"recording_id": recording.id, "force": data.force})
        queued += 1
    if queued == 0:
        raise HTTPException(
            status_code=409, detail="Analysis is already running for every table of this round"
        )
    record_audit_event(
        session, "analysis_requested", "round", round_.id, actor=user,
        data={"recordings": queued, "force": data.force},
    )
    return {"queued": queued}
