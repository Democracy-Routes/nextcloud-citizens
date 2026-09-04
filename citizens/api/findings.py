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
from citizens.services import provider_config
from citizens.services.analysis import analysis_ready
from citizens.services.assemblies import get_owned_round
from citizens.services.audit import record_audit_event
from citizens.services.jobs import enqueue_job

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
    recordings = {
        number: {"id": rec.id, "state": rec.state} for number, rec in recordings_full.items()
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
        "tables": tables_payload,
    }


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
    the report's methodology note asserts, and it is also load-bearing —
    _delete_existing(only_drafts=True) means approving a finding is what
    protects it from being regenerated by the next analysis run.

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
