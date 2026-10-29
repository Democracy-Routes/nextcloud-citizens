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
NOT_CONFIGURED = "AI analysis is not configured — add an analysis API key in Settings"


class SeedIn(BaseModel):
    text: str = Field(min_length=1, max_length=SEED_MAX_CHARS)


class SeedUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=SEED_MAX_CHARS)
    status: Literal["DRAFT", "APPROVED", "REJECTED"] | None = None


class OrderIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)


def _seed(session: Session, assembly_id: str, seed_id: str) -> StatementSeed:
    seed = session.get(StatementSeed, seed_id)
    if seed is None or seed.assembly_id != assembly_id:
        raise HTTPException(status_code=404, detail="Statement not found")
    return seed


def _job(session: Session, assembly_id: str) -> dict | None:
    job: AppJob | None = job_failures.latest_jobs(session, JOB_TYPE, "assembly_id", {assembly_id}).get(
        assembly_id
    )
    return job_failures.describe(job) if job is not None else None


def _listing(session: Session, assembly) -> dict:
    rows = seeds_svc.list_seeds(session, assembly.id)
    return {
        "assembly_id": assembly.id,
        "language": assembly.language,
        "analysis_configured": provider_config.analysis_ready_cached(),
        "findings_approved": seeds_svc.approved_count(session, assembly.id),
        "ready_to_export": seeds_svc.ready_to_export(rows),
        "max_chars": SEED_MAX_CHARS,
        "soft_chars": SEED_SOFT_CHARS,
        "job": _job(session, assembly.id),
        "seeds": [seeds_svc.payload(s) for s in rows],
    }


@router.get("")
def list_seeds(assembly_id: str, user: CurrentUser, session: DB):
    assembly = get_owned_assembly(session, assembly_id, user)
    return _listing(session, assembly)


@router.post("/generate", status_code=202)
def generate_seeds(assembly_id: str, user: CurrentUser, session: DB):
    """Queue the model run. Untouched drafts are replaced; reviewed, edited
    and hand-written statements stay."""
    assembly = get_owned_assembly(session, assembly_id, user)
    if not provider_config.analysis_ready_cached():
        raise HTTPException(status_code=409, detail=NOT_CONFIGURED)
    if not seeds_svc.source_findings(session, assembly):
        raise HTTPException(status_code=409, detail="Approve some findings first")
    if has_live_job(session, JOB_TYPE, "assembly_id", assembly.id):
        return {"queued": False}
    enqueue_job(session, JOB_TYPE, {"assembly_id": assembly.id}, max_attempts=3)
    record_audit_event(session, "seeds_generation_requested", "assembly", assembly.id, actor=user)
    return {"queued": True}


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
