# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organizer API: Polis statement seeds — generate, review, order, export."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from citizens.api.downloads import download_headers
from citizens.db.models import AppJob, StatementSeed
from citizens.db.models.base import utcnow
from citizens.db.models.seeds import SEED_MAX_CHARS, SEED_SOFT_CHARS
from citizens.db.session import get_db
from citizens.security.identity import CurrentUser
from citizens.services import job_failures, provider_config
from citizens.services import seeds as seeds_svc
from citizens.services.assemblies import get_owned_assembly
from citizens.services.audit import record_audit_event
from citizens.services.jobs import enqueue_job, has_live_job

router = APIRouter(prefix="/assemblies/{assembly_id}/seeds")

DB = Annotated[Session, Depends(get_db, scope="function")]

JOB_TYPE = "SEED_STATEMENTS"
PUSH_JOB = "PUSH_POLIS"
NOT_CONFIGURED = "AI analysis is not configured — add an analysis API key in Settings"


class SeedIn(BaseModel):
    text: str = Field(min_length=1, max_length=SEED_MAX_CHARS)


class SeedUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=SEED_MAX_CHARS)
    status: Literal["DRAFT", "APPROVED", "REJECTED"] | None = None


class OrderIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)


class GenerateIn(BaseModel):
    # how many statements in all; the listing's recommended_target when absent
    target: int | None = Field(default=None, ge=seeds_svc.TARGET_MIN, le=seeds_svc.TARGET_MAX)


def _seed(session: Session, assembly_id: str, seed_id: str) -> StatementSeed:
    seed = session.get(StatementSeed, seed_id)
    if seed is None or seed.assembly_id != assembly_id:
        raise HTTPException(status_code=404, detail="Statement not found")
    return seed


def _job(session: Session, assembly_id: str, job_type: str = JOB_TYPE) -> dict | None:
    job: AppJob | None = job_failures.latest_jobs(session, job_type, "assembly_id", {assembly_id}).get(
        assembly_id
    )
    return job_failures.describe(job) if job is not None else None


def _polis(session: Session, assembly, rows: list[StatementSeed]) -> dict:
    """The push's state for the listing: links once sent, the job while it
    runs or after it failed, and which statements Polis refused."""
    from citizens.services import polis as polis_svc

    job = _job(session, assembly.id, PUSH_JOB)
    refused: list[str] = []
    if job and job["state"] == "FAILED":
        positions = set(polis_svc.refused_positions(job.get("failure_detail")))
        if positions:
            # the export numbering: exportable statements in listing order
            exportable = seeds_svc.exportable(rows)
            refused = [s.id for number, s in enumerate(exportable, start=1) if number in positions]
    return {
        "configured": provider_config.polis_ready_cached(),
        "conversation_id": assembly.polis_conversation_id,
        "url": assembly.polis_url,
        "moderation_url": assembly.polis_moderation_url,
        "report_url": assembly.polis_report_url,
        "pushed_at": polis_svc.iso(assembly.polis_pushed_at),
        "published_at": polis_svc.iso(assembly.polis_published_at),
        "job": job,
        "refused_seed_ids": refused,
    }


def _listing(session: Session, assembly) -> dict:
    rows = seeds_svc.list_seeds(session, assembly.id)
    source_count = len(seeds_svc.source_findings(session, assembly))
    titles = seeds_svc.finding_titles(session, rows)
    return {
        "assembly_id": assembly.id,
        "language": assembly.language,
        "analysis_configured": provider_config.analysis_ready_cached(),
        "findings_approved": seeds_svc.approved_count(session, assembly.id),
        # the findings the statements are written from (cross-table ones when
        # the session was clustered), and how many statements to ask for
        "source_findings": source_count,
        "recommended_target": seeds_svc.recommended_target(source_count),
        "seeds_target": assembly.seeds_target,
        "target_min": seeds_svc.TARGET_MIN,
        "target_max": seeds_svc.TARGET_MAX,
        "target_step": seeds_svc.TARGET_STEP,
        "seconds_per_vote": seeds_svc.SECONDS_PER_VOTE,
        "ready_to_export": seeds_svc.ready_to_export(rows),
        "max_chars": SEED_MAX_CHARS,
        "soft_chars": SEED_SOFT_CHARS,
        "job": _job(session, assembly.id),
        "polis": _polis(session, assembly, rows),
        "seeds": [seeds_svc.payload(s, titles.get(s.finding_id or "")) for s in rows],
    }


@router.get("")
def list_seeds(assembly_id: str, user: CurrentUser, session: DB):
    assembly = get_owned_assembly(session, assembly_id, user)
    return _listing(session, assembly)


@router.post("/generate", status_code=202)
def generate_seeds(assembly_id: str, user: CurrentUser, session: DB, data: GenerateIn | None = None):
    """Queue the model run. Untouched drafts are replaced; reviewed, edited
    and hand-written statements stay. `target` is how many statements in
    all; the listing's recommendation when not given."""
    assembly = get_owned_assembly(session, assembly_id, user)
    if not provider_config.analysis_ready_cached():
        raise HTTPException(status_code=409, detail=NOT_CONFIGURED)
    if not seeds_svc.source_findings(session, assembly):
        raise HTTPException(status_code=409, detail="Approve some findings first")
    if has_live_job(session, JOB_TYPE, "assembly_id", assembly.id):
        return {"queued": False}
    target = data.target if data is not None else None
    enqueue_job(session, JOB_TYPE, {"assembly_id": assembly.id, "target": target}, max_attempts=3)
    record_audit_event(
        session, "seeds_generation_requested", "assembly", assembly.id, actor=user,
        data={"target": target},
    )
    return {"queued": True, "target": target}


@router.post("/approve-all")
def approve_all_seeds(assembly_id: str, user: CurrentUser, session: DB):
    """Every draft becomes approved in one go — the plenary case, where the
    statements must reach Polis minutes after the last table ends. Rejected
    and exported statements are left as they are."""
    assembly = get_owned_assembly(session, assembly_id, user)
    if has_live_job(session, JOB_TYPE, "assembly_id", assembly.id):
        raise HTTPException(status_code=409, detail="Statements are still being generated")
    rows = seeds_svc.list_seeds(session, assembly.id)
    drafts = [s for s in rows if s.status == "DRAFT"]
    now = utcnow()
    for seed in drafts:
        seed.status = "APPROVED"
        seed.reviewed_by = user
        seed.reviewed_at = now
    if drafts:
        record_audit_event(
            session, "seeds_approved_all", "assembly", assembly.id, actor=user,
            data={"approved": len(drafts)},
        )
    listing = _listing(session, assembly)
    listing["approved"] = len(drafts)
    return listing


@router.post("", status_code=201)
def create_seed(assembly_id: str, data: SeedIn, user: CurrentUser, session: DB):
    assembly = get_owned_assembly(session, assembly_id, user)
    seed = StatementSeed(
        assembly_id=assembly.id,
        text=" ".join(data.text.split()),
        source_text="",
        language=assembly.language,
        position=seeds_svc.next_position(session, assembly.id),
        origin="manual",
        reviewed_by=user,
        reviewed_at=utcnow(),
    )
    session.add(seed)
    session.flush()
    record_audit_event(session, "seed_added", "statement_seed", seed.id, actor=user)
    return seeds_svc.payload(seed)


@router.put("/order")
def reorder_seeds(assembly_id: str, data: OrderIn, user: CurrentUser, session: DB):
    """`ids` in the wanted order; statements not named keep their relative
    order after them."""
    assembly = get_owned_assembly(session, assembly_id, user)
    rows = seeds_svc.list_seeds(session, assembly.id)
    by_id = {s.id: s for s in rows}
    unknown = [i for i in data.ids if i not in by_id]
    if unknown:
        raise HTTPException(status_code=404, detail="Statement not found")
    ordered = [by_id[i] for i in dict.fromkeys(data.ids)]
    ordered += [s for s in rows if s.id not in set(data.ids)]
    for number, seed in enumerate(ordered, start=1):
        seed.position = number
    return {"seeds": [seeds_svc.payload(s) for s in ordered]}


@router.put("/{seed_id}")
def update_seed(assembly_id: str, seed_id: str, data: SeedUpdate, user: CurrentUser, session: DB):
    assembly = get_owned_assembly(session, assembly_id, user)
    seed = _seed(session, assembly.id, seed_id)
    if data.text is not None:
        seed.text = " ".join(data.text.split())
        if not seed.text:
            raise HTTPException(status_code=422, detail="A statement cannot be empty")
        seed.stale = False
    if data.status is not None:
        seed.status = data.status
    if data.text is not None or data.status is not None:
        seed.reviewed_by = user
        seed.reviewed_at = utcnow()
        record_audit_event(
            session, "seed_reviewed", "statement_seed", seed.id, actor=user,
            data={"status": seed.status, "edited": seed.edited},
        )
    return seeds_svc.payload(seed)


@router.delete("/{seed_id}", status_code=204)
def delete_seed(assembly_id: str, seed_id: str, user: CurrentUser, session: DB):
    assembly = get_owned_assembly(session, assembly_id, user)
    seed = _seed(session, assembly.id, seed_id)
    session.delete(seed)
    record_audit_event(session, "seed_deleted", "statement_seed", seed_id, actor=user)
    return None


@router.post("/push", status_code=202)
def push_seeds(assembly_id: str, user: CurrentUser, session: DB):
    """Queue the send to the configured Polis instance; the job does the
    network work. Same gate as the export: the review must be finished."""
    assembly = get_owned_assembly(session, assembly_id, user)
    if not provider_config.polis_ready_cached():
        raise HTTPException(
            status_code=409,
            detail="Polis is not configured — add the instance URL and API key in Settings",
        )
    rows = seeds_svc.list_seeds(session, assembly.id)
    if not seeds_svc.ready_to_export(rows):
        raise HTTPException(
            status_code=409,
            detail="Review every statement — approve or reject each one — before sending",
        )
    if has_live_job(session, PUSH_JOB, "assembly_id", assembly.id):
        return {"queued": False}
    enqueue_job(session, PUSH_JOB, {"assembly_id": assembly.id}, max_attempts=3)
    record_audit_event(
        session, "seeds_push_requested", "assembly", assembly.id, actor=user,
        data={"statements": len(seeds_svc.exportable(rows))},
    )
    return {"queued": True}


@router.post("/poll/publish")
def publish_poll(assembly_id: str, user: CurrentUser, session: DB):
    """Put the Polis voting link on the table phones (and the participants'
    own pages): the recorder shows it with a QR code, like the report."""
    assembly = get_owned_assembly(session, assembly_id, user)
    if not assembly.polis_url:
        raise HTTPException(status_code=409, detail="Send the statements to Polis first")
    assembly.polis_published_at = utcnow()
    record_audit_event(session, "polis_poll_published", "assembly", assembly.id, actor=user)
    return {"published_at": assembly.polis_published_at.isoformat()}


@router.delete("/poll/publish", status_code=204)
def unpublish_poll(assembly_id: str, user: CurrentUser, session: DB):
    assembly = get_owned_assembly(session, assembly_id, user)
    assembly.polis_published_at = None
    record_audit_event(session, "polis_poll_unpublished", "assembly", assembly.id, actor=user)
    return None


@router.get("/poll-qr")
def poll_qr(assembly_id: str, user: CurrentUser, session: DB):
    """The voting link as a QR for the organizer's QR tab, once sent."""
    from citizens.services import invites as invites_svc
    from citizens.services import polis as polis_svc

    assembly = get_owned_assembly(session, assembly_id, user)
    if not assembly.polis_url:
        return {"available": False, "published": False, "url": None, "qr_svg": None}
    return {
        "available": True,
        "published": assembly.polis_published_at is not None,
        "published_at": polis_svc.iso(assembly.polis_published_at),
        "url": assembly.polis_url,
        "qr_svg": invites_svc.qr_svg(assembly.polis_url),
    }


def _export(session: Session, assembly_id: str, user: str, ext: str) -> Response:
    assembly = get_owned_assembly(session, assembly_id, user)
    rows = seeds_svc.list_seeds(session, assembly.id)
    if not seeds_svc.ready_to_export(rows):
        raise HTTPException(
            status_code=409,
            detail="Review every statement — approve or reject each one — before exporting",
        )
    chosen = seeds_svc.exportable(rows)
    when = seeds_svc.mark_exported(chosen)
    if ext == "csv":
        body, media = seeds_svc.render_csv(chosen), "text/csv; charset=utf-8"
    else:
        body, media = seeds_svc.render_json(assembly, chosen, when), "application/json; charset=utf-8"
    record_audit_event(
        session, "seeds_exported", "assembly", assembly.id, actor=user,
        data={"format": ext, "statements": len(chosen)},
    )
    return Response(
        body.encode("utf-8"),
        media_type=media,
        headers=download_headers(seeds_svc.export_filename(assembly, ext)),
    )


@router.get("/export.csv")
def export_csv(assembly_id: str, user: CurrentUser, session: DB):
    """Approved statements, one per row, for the Polis seed box or import."""
    return _export(session, assembly_id, user, "csv")


@router.get("/export.json")
def export_json(assembly_id: str, user: CurrentUser, session: DB):
    return _export(session, assembly_id, user, "json")
