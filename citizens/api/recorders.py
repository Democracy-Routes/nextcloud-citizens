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
from citizens.db.models import RecorderSession, Recording, Table
from citizens.db.models.base import utcnow
from citizens.db.session import get_db, get_read_db
from citizens.domain import schemas
from citizens.jobs.handlers import maybe_enqueue_round_analysis
from citizens.security.identity import CurrentUser
from citizens.services import invites as invite_svc
from citizens.services import live_source
from citizens.services.assemblies import get_owned_assembly, get_owned_round
from citizens.services.audit import record_audit_event
from citizens.services.jobs import enqueue_job, has_live_job
from citizens.services.live_captions import LIVE_CAPTIONS
from citizens.services.recording import salvage_total_chunks
from citizens.services.recording_states import transition
from citizens.services.table_recordings import recording_slots, recordings_for_table, slot_label
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


#: states a recording can be in when its phone has stopped talking to us
STALLED_STATES = ("WAITING_FOR_CHUNKS", "RECORDING", "FINALIZING", "ASSEMBLING")


def _owned_stalled_recording(session: Session, recording_id: str, user: str) -> Recording:
    """The caller's recording, if it is one that can be given up on."""
    recording = session.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    get_owned_assembly(session, recording.assembly_id, user)
    # ASSEMBLING included: a recording whose assembly failed for good (a full
    # disk, exhausted retries) is stuck there with nothing else able to free it
    if recording.state not in STALLED_STATES:
        raise HTTPException(
            status_code=409,
            detail=f"Recording is {recording.state}; only a stalled upload can be given up on",
        )
    if recording.state == "ASSEMBLING" and has_live_job(
        session, "ASSEMBLE_AUDIO", "recording_id", recording.id
    ):
        raise HTTPException(
            status_code=409,
            detail="This recording is still being assembled; wait for it to finish or fail",
        )
    return recording


def release_stalled_recording(session: Session, recording: Recording, error_code: str) -> None:
    """Stop waiting for this recording's phone, and close its caption session.

    Shared by every path that gives up on a device — the organizer abandoning
    an upload, the organizer replacing a dead phone, and a replacement device
    taking over automatically. They differ only in what they do afterwards and
    in the error code they leave behind, which is what tells the organizer
    which of them happened.

    Ending the caption session matters on all three: /complete is the only
    other thing that ever ends one, and a phone that is not coming back will
    never send it. Left running it holds a provider websocket open and never
    writes down what it heard.
    """
    recording.error_code = error_code
    transition(recording, "UPLOAD_INCOMPLETE")
    session.flush()
    # a backup recorder still recording takes over the live captions
    live_source.release(session, recording)
    LIVE_CAPTIONS.finish(recording.id)


@router.post("/recordings/{recording_id}/promote-live-source")
def promote_live_source(recording_id: str, user: CurrentUser, session: DB):
    """Make this recording the one that feeds its table's live captions.

    For a table with more than one recorder phone: the organizer picks which
    one the room reads. The previous holder keeps recording; only its caption
    session ends."""
    recording = session.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    get_owned_assembly(session, recording.assembly_id, user)
    demoted = live_source.promote(session, recording)
    record_audit_event(
        session, "live_source_promoted", "recording", recording.id, actor=user,
        data={"from_recording_id": demoted.id if demoted is not None else None},
    )
    session.flush()
    if demoted is not None:
        LIVE_CAPTIONS.finish(demoted.id)
    return {"recording_id": recording.id, "live_source": True}


@router.post("/recordings/{recording_id}/abandon-upload")
def abandon_upload(recording_id: str, user: CurrentUser, session: DB):
    """Stop waiting for a table whose phone never finished uploading.

    A stalled upload is swept automatically after a while, but during a live
    event the organizer needs to move the round on now rather than wait. The
    audio already received is kept, and the table can still re-record or the
    phone can still finish uploading later — UPLOAD_INCOMPLETE transitions back.
    """
    recording = _owned_stalled_recording(session, recording_id, user)
    release_stalled_recording(session, recording, "UPLOAD_ABANDONED")
    maybe_enqueue_round_analysis(session, recording)
    record_audit_event(
        session, "upload_abandoned", "recording", recording.id, actor=user,
        data={"received_chunks": recording.received_chunks, "total_chunks": recording.total_chunks},
    )
    return {"state": recording.state}


@router.post("/recordings/{recording_id}/replace-device")
def replace_device(recording_id: str, user: CurrentUser, session: DB):
    """This table's phone is gone; let another one take over.

    Distinct from abandon-upload, which means "stop waiting, it may yet come
    back". This means a person walked to the table and saw a dead phone, and
    that confidence buys two things abandon does not do:

      * the partial recording is assembled and transcribed immediately, so most
        of the round becomes a real transcript instead of waiting for somebody
        to remember a manual Retry afterwards;
      * the table is released at once, rather than in twenty minutes, which on
        a thirty-minute round is the difference between recording the rest of
        the discussion and losing it.

    The replacement phone simply rescans the SAME QR code — invites are not
    single-use — and starts a second recording for this table and round.

    The old phone's session is deliberately NOT revoked. If it is charged
    later, its unsent chunks are all from before it died, so they belong to
    this recording and overlap nothing; revoking would strand them, because
    uploading them needs its bearer token.
    """
    recording = _owned_stalled_recording(session, recording_id, user)
    release_stalled_recording(session, recording, "DEVICE_REPLACED")
    # Marked BEFORE assembly is queued: the recording is about to move through
    # ASSEMBLING and on to a transcript, none of which are re-recordable
    # states, so without this the replacement phone would still be refused —
    # the feature would defeat itself.
    recording.superseded_at = utcnow()

    # Assemble what can still become audio: the contiguous chunk prefix.
    # The old reasoning — "missing_sequences() returns [] when total_chunks is
    # NULL" — was inverted for WAITING_FOR_CHUNKS, the first state on this
    # endpoint's own list: a recording is there precisely BECAUSE /complete
    # declared chunks that never arrived, so the assemble job bounced it
    # straight back and the salvaged audio could never be used by anything.
    salvaged = salvage_total_chunks(session, recording)
    assembling = salvaged > 0
    if assembling:
        recording.total_chunks = salvaged
        transition(recording, "ASSEMBLING")
        enqueue_job(session, "ASSEMBLE_AUDIO", {"recording_id": recording.id})
    else:
        # nothing to assemble, so the round should stop waiting on this table
        maybe_enqueue_round_analysis(session, recording)

    record_audit_event(
        session, "device_replaced", "recording", recording.id, actor=user,
        data={
            "table_number": recording.table_number,
            "received_chunks": recording.received_chunks,
            "salvaged_chunks": salvaged,
            "assembling": assembling,
        },
    )
    return {"state": recording.state, "assembling": assembling, "salvaged_chunks": salvaged}


@router.post("/recordings/{recording_id}/assemble", status_code=202)
def retry_assembly(recording_id: str, user: CurrentUser, session: DB):
    """Try assembling this recording's audio again.

    The only other place that ever enqueues ASSEMBLE_AUDIO is
    complete_recording, which refuses a recording that is already ASSEMBLING —
    so when assembly failed for good (a full disk exhausting the retries) there
    was nothing an organizer could do about it. The chunks are still on disk;
    once space is free this is the way back.
    """
    recording = session.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    get_owned_assembly(session, recording.assembly_id, user)
    if recording.state not in ("ASSEMBLING", "AUDIO_INVALID", "UPLOAD_INCOMPLETE"):
        raise HTTPException(
            status_code=409,
            detail=f"Recording is {recording.state}; there is nothing to assemble",
        )
    if has_live_job(session, "ASSEMBLE_AUDIO", "recording_id", recording.id):
        raise HTTPException(
            status_code=409, detail="Assembly is already queued for this recording"
        )
    salvaged: int | None = None
    if recording.state == "UPLOAD_INCOMPLETE":
        # The phone is gone: what the server holds is all there will be. Same
        # salvage as Replace device — declare the contiguous prefix the whole
        # recording. Without it a recording whose /complete had declared more
        # chunks than arrived bounced straight back to WAITING_FOR_CHUNKS, the
        # sweep timed it out again twenty minutes later, and Retry looped.
        salvaged = salvage_total_chunks(session, recording)
        if salvaged == 0:
            raise HTTPException(
                status_code=409,
                detail="No audio reached the server for this recording; there is nothing to assemble",
            )
        recording.total_chunks = salvaged
    if recording.state != "ASSEMBLING":
        transition(recording, "ASSEMBLING")
    recording.error_code = ""
    session.flush()
    enqueue_job(session, "ASSEMBLE_AUDIO", {"recording_id": recording.id})
    record_audit_event(
        session, "assembly_retried", "recording", recording.id, actor=user,
        data={"table_number": recording.table_number, "salvaged_chunks": salvaged},
    )
    return {"state": recording.state, "salvaged_chunks": salvaged}

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


@router.get("/assemblies/{assembly_id}/event-kit.pdf")
def event_kit_pdf(assembly_id: str, user: CurrentUser, session: ReadDB):
    """The printable event kit: one card per table (number, colour band, QR),
    the programme of sessions, and the recording notice in the assembly's
    language. Printed the evening before; see services/event_kit.py."""
    from fastapi.responses import Response

    from citizens.services.branding import logo_path, organization_name
    from citizens.services.event_kit import render_event_kit
    from citizens.services.provider_config import data_handling_summary

    assembly = get_owned_assembly(session, assembly_id, user)
    cards = invite_svc.invite_links(session, assembly)
    rounds = [
        {
            "position": round_.position,
            "title": round_.title,
            "question": round_.question,
            "objective": round_.objective,
            "duration_minutes": round_.duration_minutes,
        }
        for round_ in assembly.rounds
    ]
    handling = data_handling_summary()
    if assembly.audio_retention_days is not None:
        handling = {**handling, "audio_retention_days": assembly.audio_retention_days}
    pdf = render_event_kit(
        assembly.name, assembly.language, cards, rounds, handling, logo_path(), organization_name()
    )
    filename = f"{assembly.name[:40].replace(' ', '-')}-event-kit.pdf"
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


@router.get("/rounds/{round_id}/tables/{table_id}/recordings")
def table_recordings(round_id: str, table_id: str, user: CurrentUser, session: ReadDB):
    """Every recording of one table's discussion in one round — however many
    phones made them — with the recorder slot each came from."""
    round_ = get_owned_round(session, round_id, user)
    table = session.get(Table, table_id)
    if table is None or table.round_id != round_.id:
        raise HTTPException(status_code=404, detail="Table not found")
    recordings = recordings_for_table(session, round_.id, table.id)
    slots = recording_slots(session, recordings)
    return [
        {
            "id": recording.id,
            "slot": slots.get(recording.id, 1),
            "slot_label": slot_label(slots.get(recording.id, 1)),
            "state": recording.state,
            "error_code": recording.error_code,
            "started_at": recording.started_at,
            "ended_at": recording.ended_at,
            "duration_seconds": recording.duration_seconds,
            "superseded_at": recording.superseded_at,
            "received_chunks": recording.received_chunks,
        }
        for recording in recordings
    ]


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
