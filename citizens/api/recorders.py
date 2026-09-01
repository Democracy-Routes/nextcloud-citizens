# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organizer API for recorder invites/QR codes and device diagnostics."""

from collections import deque
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.api.downloads import download_headers
from citizens.config import get_settings
from citizens.db.models import RecorderSession, Recording
from citizens.db.session import get_db, get_read_db
from citizens.domain import schemas
from citizens.jobs.handlers import maybe_enqueue_round_analysis
from citizens.security.identity import CurrentUser
from citizens.services import invites as invite_svc
from citizens.services.assemblies import get_owned_assembly
from citizens.services.audit import record_audit_event
from citizens.services.recording_states import transition
from citizens.storage.paths import device_log_path

router = APIRouter()

DB = Annotated[Session, Depends(get_db)]
# Listing invites and rendering the QR sheet are reads; the sheet in particular
# renders a PDF, which must not hold the writer slot while tables are joining.
ReadDB = Annotated[Session, Depends(get_read_db)]


@router.get("/assemblies/{assembly_id}/invites", response_model=list[schemas.InviteOut])
def list_invites(assembly_id: str, user: CurrentUser, session: ReadDB):
    get_owned_assembly(session, assembly_id, user)
    return invite_svc.list_invites(session, assembly_id)


@router.post("/recordings/{recording_id}/abandon-upload")
def abandon_upload(recording_id: str, user: CurrentUser, session: DB):
    """Stop waiting for a table whose phone never finished uploading.

    A stalled upload is swept automatically after a while, but during a live
    event the organizer needs to move the round on now rather than wait. The
    audio already received is kept, and the table can still re-record or the
    phone can still finish uploading later — UPLOAD_INCOMPLETE transitions back.
    """
    recording = session.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    get_owned_assembly(session, recording.assembly_id, user)
    if recording.state not in ("WAITING_FOR_CHUNKS", "RECORDING", "FINALIZING"):
        raise HTTPException(
            status_code=409,
            detail=f"Recording is {recording.state}; only a stalled upload can be abandoned",
        )
    recording.error_code = "UPLOAD_ABANDONED"
    transition(recording, "UPLOAD_INCOMPLETE")
    session.flush()
    maybe_enqueue_round_analysis(session, recording)
    record_audit_event(
        session, "upload_abandoned", "recording", recording.id, actor=user,
        data={"received_chunks": recording.received_chunks, "total_chunks": recording.total_chunks},
    )
    return {"state": recording.state}


@router.get(
    "/assemblies/{assembly_id}/invites/links",
    response_model=list[schemas.InviteGenerated],
)
def invite_links(assembly_id: str, user: CurrentUser, session: ReadDB):
    """Re-materialized QR sheet for the active invites (tokens are stored
    encrypted with the app secret; invites from before that existed are
    omitted and need a regenerate)."""
    assembly = get_owned_assembly(session, assembly_id, user)
    return invite_svc.invite_links(session, assembly)


@router.get("/assemblies/{assembly_id}/invites/sheet.pdf")
def invite_sheet_pdf(assembly_id: str, user: CurrentUser, session: ReadDB):
    """The printable QR sheet: four tables per A4 page, with cut lines.

    Built here rather than with the browser's print, which silently dropped
    every page after the first.
    """
    from fastapi.responses import Response

    from citizens.services.branding import logo_path, organization_name
    from citizens.services.qr_sheet import render_qr_sheet

    assembly = get_owned_assembly(session, assembly_id, user)
    cards = invite_svc.invite_links(session, assembly)
    pdf = render_qr_sheet(assembly.name, cards, logo_path(), organization_name())
    filename = f"{assembly.name[:40].replace(' ', '-')}-table-codes.pdf"
    return Response(pdf, media_type="application/pdf", headers=download_headers(filename))


@router.post(
    "/assemblies/{assembly_id}/invites/generate",
    response_model=list[schemas.InviteGenerated],
    status_code=201,
)
def generate_invites(assembly_id: str, user: CurrentUser, session: DB):
    """Returns fresh invite URLs + QR SVGs.
    Any previously active invites for this assembly are revoked."""
    assembly = get_owned_assembly(session, assembly_id, user)
    generated = invite_svc.generate_invites(session, assembly)
    record_audit_event(
        session, "invites_generated", "assembly", assembly.id, actor=user, data={"count": len(generated)}
    )
    return generated


@router.post("/assemblies/{assembly_id}/invites/revoke", status_code=204)
def revoke_invites(assembly_id: str, user: CurrentUser, session: DB):
    assembly = get_owned_assembly(session, assembly_id, user)
    count = invite_svc.revoke_invites(session, assembly.id)
    record_audit_event(
        session, "invites_revoked", "assembly", assembly.id, actor=user, data={"count": count}
    )


@router.get("/assemblies/{assembly_id}/tables/{table_number}/device-logs")
def device_logs(
    assembly_id: str,
    table_number: int,
    user: CurrentUser,
    session: ReadDB,
    tail: Annotated[int, Query(ge=1, le=1000)] = 200,
):
    """Tail of the latest device's shipped client log for one table."""
    get_owned_assembly(session, assembly_id, user)
    recorder_session = session.execute(
        select(RecorderSession)
        .where(
            RecorderSession.assembly_id == assembly_id,
            RecorderSession.table_number == table_number,
        )
        .order_by(RecorderSession.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if recorder_session is None:
        return {"session_id": None, "lines": []}
    path = device_log_path(get_settings().app_persistent_storage, recorder_session.id)
    lines: list[str] = []
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            lines = list(deque(handle, maxlen=tail))
    return {"session_id": recorder_session.id, "lines": [line.rstrip("\n") for line in lines]}
