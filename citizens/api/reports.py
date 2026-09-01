# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organizer report endpoints: JSON structure, Markdown/PDF download, publish."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from citizens.api.downloads import download_headers
from citizens.db.models.base import utcnow
from citizens.db.session import get_db, get_read_db
from citizens.security.identity import CurrentUser
from citizens.services import lifecycle
from citizens.services.assemblies import get_owned_assembly
from citizens.services.audit import record_audit_event
from citizens.services.branding import logo_path, organization_name
from citizens.services.report import build_report, render_markdown
from citizens.services.report_pdf import render_pdf

router = APIRouter()

DB = Annotated[Session, Depends(get_db)]
# Rendering a report reads every transcript and finding, and the PDF path also
# asks Nextcloud for the organization name over OCS. None of that may happen
# while holding SQLite's single writer slot.
ReadDB = Annotated[Session, Depends(get_read_db)]


def _report_filename(name: str, ext: str) -> str:
    return f"{name[:40].replace(' ', '-')}-report.{ext}"


def _require_closed(assembly) -> None:
    """Exports are the final artifact: they exist once the session is closed."""
    if assembly.closed_at is None:
        raise HTTPException(
            status_code=409,
            detail="Close the session to create the final report",
        )


@router.get("/assemblies/{assembly_id}/report")
def assembly_report(
    assembly_id: str,
    user: CurrentUser,
    session: ReadDB,
    include_drafts: Annotated[bool, Query()] = False,
):
    assembly = get_owned_assembly(session, assembly_id, user)
    return build_report(session, assembly, include_drafts=include_drafts)


@router.get("/assemblies/{assembly_id}/report.md")
def assembly_report_markdown(
    assembly_id: str,
    user: CurrentUser,
    session: ReadDB,
    include_drafts: Annotated[bool, Query()] = False,
):
    assembly = get_owned_assembly(session, assembly_id, user)
    _require_closed(assembly)
    markdown = render_markdown(build_report(session, assembly, include_drafts=include_drafts))
    return PlainTextResponse(
        markdown,
        media_type="text/markdown; charset=utf-8",
        headers=download_headers(_report_filename(assembly.name, "md")),
    )


@router.get("/assemblies/{assembly_id}/report.pdf")
def assembly_report_pdf(
    assembly_id: str,
    user: CurrentUser,
    session: ReadDB,
    include_drafts: Annotated[bool, Query()] = False,
):
    assembly = get_owned_assembly(session, assembly_id, user)
    _require_closed(assembly)
    pdf = render_pdf(
        build_report(session, assembly, include_drafts=include_drafts),
        logo_path(),
        organization_name(),
    )
    return Response(
        pdf,
        media_type="application/pdf",
        headers=download_headers(_report_filename(assembly.name, "pdf")),
    )


@router.post("/assemblies/{assembly_id}/close")
def close_session(assembly_id: str, user: CurrentUser, session: DB):
    """Finish the assembly: no more recordings, and the report becomes final
    (frozen, so reopening cannot change what participants already read)."""
    assembly = get_owned_assembly(session, assembly_id, user)
    lifecycle.close_assembly(session, assembly)
    record_audit_event(
        session, "assembly_closed", "assembly", assembly.id, actor=user,
        data=lifecycle.assembly_progress(session, assembly),
    )
    return {
        "closed_at": assembly.closed_at.isoformat(),
        "progress": lifecycle.assembly_progress(session, assembly),
    }


@router.delete("/assemblies/{assembly_id}/close", status_code=204)
def reopen_session(assembly_id: str, user: CurrentUser, session: DB):
    assembly = get_owned_assembly(session, assembly_id, user)
    lifecycle.reopen_assembly(session, assembly)
    record_audit_event(session, "assembly_reopened", "assembly", assembly.id, actor=user)


@router.post("/assemblies/{assembly_id}/report/refresh")
def refresh_final_report(assembly_id: str, user: CurrentUser, session: DB):
    """Re-freeze the published version from the current content."""
    assembly = get_owned_assembly(session, assembly_id, user)
    _require_closed(assembly)
    lifecycle.snapshot_final_report(session, assembly)
    record_audit_event(session, "final_report_refreshed", "assembly", assembly.id, actor=user)
    return {"final_report_at": assembly.final_report_at.isoformat()}


@router.get("/assemblies/{assembly_id}/progress")
def assembly_progress(assembly_id: str, user: CurrentUser, session: ReadDB):
    assembly = get_owned_assembly(session, assembly_id, user)
    return lifecycle.assembly_progress(session, assembly)


@router.post("/assemblies/{assembly_id}/report/publish")
def publish_report(assembly_id: str, user: CurrentUser, session: DB):
    """Make the report (approved findings + AI summaries) visible on the
    table recorder phones. AI drafts stay organizer-only either way."""
    assembly = get_owned_assembly(session, assembly_id, user)
    assembly.report_published_at = utcnow()
    record_audit_event(session, "report_published", "assembly", assembly.id, actor=user)
    return {"published_at": assembly.report_published_at.isoformat()}


@router.delete("/assemblies/{assembly_id}/report/publish", status_code=204)
def unpublish_report(assembly_id: str, user: CurrentUser, session: DB):
    assembly = get_owned_assembly(session, assembly_id, user)
    assembly.report_published_at = None
    record_audit_event(session, "report_unpublished", "assembly", assembly.id, actor=user)
