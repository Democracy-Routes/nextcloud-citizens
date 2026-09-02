# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public recorder API (PUBLIC AppAPI routes; recorder-session bearer auth).

A recorder session can only ever: read its assembly/round state, create
recordings for its own table, upload chunks, and complete recordings.
"""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from citizens.api.downloads import download_headers
from citizens.config import get_settings
from citizens.db.models import Assembly, RecorderSession, Recording
from citizens.db.models.base import utcnow
from citizens.db.session import get_db, get_read_db
from citizens.security.rate_limit import (
    JOIN_IP_LIMITER,
    JOIN_TOKEN_LIMITER,
    client_ip,
    token_key,
)
from citizens.services import provider_config
from citizens.services import recording as rec_svc
from citizens.services.live_captions import LIVE_CAPTIONS
from citizens.services.provider_config import data_handling_summary, live_stt_snapshot
from citizens.services.recording import MAX_CHUNK_BYTES, RERECORDABLE_STATES
from citizens.storage.paths import device_log_path

router = APIRouter(prefix="/public")

DB = Annotated[Session, Depends(get_db)]
# for pure polls: no BEGIN IMMEDIATE, so readers never queue behind writers
ReadDB = Annotated[Session, Depends(get_read_db)]


def _session_from_authorization(
    session: Session, authorization: str, touch: bool = True
) -> RecorderSession:
    scheme, _, bearer = authorization.partition(" ")
    if scheme.lower() != "bearer" or not bearer:
        raise HTTPException(status_code=401, detail="Missing recorder session token")
    return rec_svc.get_session_by_bearer(session, bearer.strip(), touch=touch)


def get_recorder_session(
    session: DB,
    authorization: Annotated[str, Header()] = "",
) -> RecorderSession:
    return _session_from_authorization(session, authorization)


def get_reading_session(
    session: ReadDB,
    authorization: Annotated[str, Header()] = "",
) -> RecorderSession:
    """Auth for poll endpoints: no write lock, and no last_seen_at write.

    Liveness still comes from the heartbeat and chunk uploads every 10-20 s,
    which is finer resolution than the monitor displays."""
    return _session_from_authorization(session, authorization, touch=False)


RecorderSess = Annotated[RecorderSession, Depends(get_recorder_session)]
ReadingSess = Annotated[RecorderSession, Depends(get_reading_session)]


class JoinIn(BaseModel):
    token: str = Field(min_length=16, max_length=128)


@router.post("/join")
def join(data: JoinIn, request: Request, session: DB):
    JOIN_TOKEN_LIMITER.check(token_key(data.token))
    JOIN_IP_LIMITER.check(client_ip(request))
    # Both of these can refresh a 30-second cache by calling Nextcloud over
    # OCS. Read them BEFORE the first statement: create_session_from_invite
    # opens the write transaction, and SQLite's single writer slot must not be
    # held across an HTTPS round-trip while the room is scanning QR codes.
    handling = data_handling_summary()
    analysis_enabled = provider_config.analysis_enabled_cached()
    recorder_session, bearer = rec_svc.create_session_from_invite(session, data.token)
    return {
        "session_token": bearer,
        "expires_at": recorder_session.expires_at,
        **_assembly_state(
            session, recorder_session, handling=handling, analysis_enabled=analysis_enabled
        ),
    }


@router.get("/recorder/status")
def status(recorder_session: ReadingSess, session: ReadDB):
    return _assembly_state(session, recorder_session)


class StartIn(BaseModel):
    round_id: str
    mime_type: str = Field(min_length=1, max_length=80)


@router.post("/recorder/start", status_code=201)
def start(data: StartIn, recorder_session: RecorderSess, session: DB):
    recording = rec_svc.start_recording(session, recorder_session, data.round_id, data.mime_type)
    return {"recording_id": recording.id, "state": recording.state}


async def _read_capped_body(request: Request) -> bytes:
    """Read the request body, refusing anything over one chunk's worth.

    Content-Length is the normal path — the recorder always sets it, so an
    oversized upload is rejected before a single byte is read. The streaming
    branch is the backstop for a chunked or lying client, and it aborts as soon
    as the accumulated body passes the limit rather than at the end.
    """
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_CHUNK_BYTES:
        raise HTTPException(status_code=413, detail="Chunk too large")
    buffer = bytearray()
    async for part in request.stream():
        buffer.extend(part)
        if len(buffer) > MAX_CHUNK_BYTES:
            raise HTTPException(status_code=413, detail="Chunk too large")
    return bytes(buffer)


@router.post("/recorder/recordings/{recording_id}/chunks/{sequence_number}")
async def upload_chunk(
    recording_id: str,
    sequence_number: int,
    request: Request,
    session: DB,
    authorization: Annotated[str, Header()] = "",
    x_chunk_sha256: Annotated[str, Header()] = "",
):
    if not x_chunk_sha256:
        raise HTTPException(status_code=400, detail="X-Chunk-SHA256 header required")
    if sequence_number < 0 or sequence_number > 100000:
        raise HTTPException(status_code=422, detail="Invalid sequence number")
    # Read the upload BEFORE touching the database. Authentication is a query,
    # and every query here opens BEGIN IMMEDIATE — SQLite's single writer slot.
    # Resolving the session as a dependency held that slot for the whole body
    # read, so one phone on congested venue WiFi stalled every other table
    # until they hit busy_timeout and got "database is locked".
    #
    # That ordering is deliberate and must stay, which is exactly why the size
    # limit has to be enforced HERE. This route is public, so before the fix an
    # unauthenticated caller could post half a gigabyte and have it buffered in
    # full before anything checked the bearer token — a handful in parallel
    # OOM-kills the container mid-assembly. The size check in receive_chunk is
    # too late to prevent that; it stays as the belt to this pair of braces.
    body = await _read_capped_body(request)

    # Everything below blocks: SQLite waits up to busy_timeout for the writer
    # slot, the chunk is written to disk, and the config read makes an OCS call
    # to Nextcloud whenever its 30-second cache expires. This is the ONLY async
    # endpoint in the app, so running any of that inline ran it on the event
    # loop — freezing the entire server, not merely this request. Ten tables
    # uploading at once made a plain redirect take 27 seconds, the organizer UI
    # stop responding, and commits (which the loop must schedule) stall until
    # waiting writers gave up with "database is locked".
    def _persist() -> tuple[dict, str, str, dict, str]:
        stt = live_stt_snapshot()
        recorder_session = _session_from_authorization(session, authorization)
        recording = rec_svc.get_session_recording(session, recorder_session, recording_id)
        outcome = rec_svc.receive_chunk(
            session, recording, sequence_number, x_chunk_sha256, body
        )
        language = ""
        if not outcome.get("duplicate"):
            assembly = session.get(Assembly, recording.assembly_id)
            language = assembly.language if assembly else ""
        return outcome, recording.id, language, stt, recording.assembly_id

    result, recording_id_out, language, stt, assembly_id = await run_in_threadpool(_persist)
    if not result.get("duplicate"):
        # provisional live captions ride on the safety upload — failures here
        # never affect the recording (brief §51)
        LIVE_CAPTIONS.feed(recording_id_out, body, stt, language, assembly_id)
    return result


class CompleteIn(BaseModel):
    total_chunks: int = Field(ge=1, le=100000)


@router.post("/recorder/recordings/{recording_id}/complete")
def complete(
    recording_id: str, data: CompleteIn, recorder_session: RecorderSess, session: DB
):
    recording = rec_svc.get_session_recording(session, recorder_session, recording_id)
    result = rec_svc.complete_recording(session, recording, data.total_chunks)
    if not result["missing_sequences"]:
        LIVE_CAPTIONS.finish(recording.id)
    return result


@router.get("/recorder/recordings/{recording_id}/live")
def live_transcript(recording_id: str, recorder_session: ReadingSess, session: ReadDB):
    """Provisional live captions for this table's recording (may be empty or
    unavailable — that is never an error)."""
    recording = rec_svc.get_session_recording(session, recorder_session, recording_id)
    return LIVE_CAPTIONS.status(recording.id)


@router.get("/recorder/recordings/{recording_id}")
def recording_status(recording_id: str, recorder_session: RecorderSess, session: DB):
    recording = rec_svc.get_session_recording(session, recorder_session, recording_id)
    return rec_svc.recording_status(session, recording)


def _published_report(session: Session, recorder_session: RecorderSession) -> tuple:
    from citizens.services.lifecycle import frozen_report
    from citizens.services.report import build_report

    assembly = session.get(Assembly, recorder_session.assembly_id)
    if assembly is None or not _report_available(session, assembly):
        raise HTTPException(status_code=404, detail="No published report for this assembly")
    # once the session was closed, participants read the frozen version — a
    # later reopening must never change the report under them
    snapshot = frozen_report(assembly)
    if snapshot is not None:
        return assembly, snapshot
    # approved findings only — AI drafts never reach participants
    return assembly, build_report(session, assembly, include_drafts=False)


@router.get("/recorder/report")
def published_report(recorder_session: ReadingSess, session: ReadDB):
    _, report = _published_report(session, recorder_session)
    return report


@router.get("/recorder/report.pdf")
def published_report_pdf(recorder_session: ReadingSess, session: ReadDB):
    from fastapi.responses import Response

    from citizens.services.branding import logo_path, organization_name
    from citizens.services.report_pdf import render_pdf

    assembly, report = _published_report(session, recorder_session)
    filename = f"{assembly.name[:40].replace(' ', '-')}-report.pdf"
    return Response(
        render_pdf(report, logo_path(), organization_name()),
        media_type="application/pdf",
        headers=download_headers(filename),
    )


class HeartbeatIn(BaseModel):
    recording_id: str | None = None
    recording_active: bool = False
    armed: bool = False
    local_chunks: int = Field(default=0, ge=0)
    acked_chunks: int = Field(default=0, ge=0)
    storage_ok: bool = True
    storage_free_mb: float | None = None
    # how many recordings this phone still holds locally, so the organizer can
    # see how far a purge actually reached rather than assume it reached all
    local_recordings: int | None = Field(default=None, ge=0)
    # 0.0–1.0, or absent. Only Chromium exposes the Battery API, so a table
    # reporting nothing means "unknown", never "fine" — the monitor must not
    # imply otherwise.
    battery_level: float | None = Field(default=None, ge=0.0, le=1.0)


@router.post("/recorder/heartbeat")
def heartbeat(data: HeartbeatIn, recorder_session: RecorderSess, session: DB):
    recorder_session.last_status_json = data.model_dump_json()
    recorder_session.last_status_at = utcnow()
    return {"ok": True}


class LogEntry(BaseModel):
    ts: float
    level: str = Field(max_length=10)
    event: str = Field(max_length=120)
    data: dict | None = None


class LogsIn(BaseModel):
    entries: list[LogEntry] = Field(max_length=200)


MAX_DEVICE_LOG_BYTES = 5 * 1024 * 1024


@router.post("/recorder/logs")
def ship_logs(data: LogsIn, recorder_session: RecorderSess):
    """Offline-tolerant client log shipping — the recorder's diagnostic trail
    for devices nobody can attach devtools to."""
    path = device_log_path(get_settings().app_persistent_storage, recorder_session.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > MAX_DEVICE_LOG_BYTES:
        return {"accepted": 0, "truncated": True}
    with path.open("a", encoding="utf-8") as handle:
        for entry in data.entries:
            line = json.dumps(entry.model_dump(exclude_none=True))[:2048]
            handle.write(line + "\n")
    return {"accepted": len(data.entries), "truncated": False}


def _assembly_state(
    session: Session,
    recorder_session: RecorderSession,
    handling: dict | None = None,
    analysis_enabled: bool | None = None,
) -> dict:
    """Everything a phone needs about its assembly.

    `handling` and `analysis_enabled` may be passed by a caller that already
    read them outside its transaction (see join); left None they are read here,
    which is correct for the status poll because that runs on a read session.
    """
    assembly = session.get(Assembly, recorder_session.assembly_id)
    if assembly is None:
        raise HTTPException(status_code=404, detail="Assembly not found")
    # this table's recording state per round, so the phone can lock finished
    # rounds and offer only un-recorded ones — plus this table's own AI
    # summary once analysis lands (shown on the final screen)
    if handling is None:
        handling = data_handling_summary()
    recorded_rounds: dict[str, str] = {}
    table_summaries: dict[str, str] = {}
    for recording in session.execute(
        select(Recording).where(
            Recording.assembly_id == assembly.id,
            Recording.table_number == recorder_session.table_number,
            Recording.state.notin_(RERECORDABLE_STATES),
        )
    ).scalars():
        recorded_rounds[recording.round_id] = recording.state
        if recording.analysis_summary:
            table_summaries[recording.round_id] = recording.analysis_summary
    return {
        "assembly": {
            "id": assembly.id,
            "name": assembly.name,
            "language": assembly.language,
            "recording_mode": assembly.recording_mode,
        },
        # phones learn about report availability through the status poll
        "report_available": _report_available(session, assembly, analysis_enabled),
        # what the table is told before recording starts (brief §43): engine
        # name, whether it is a hosted service, and how long audio is kept
        "data_handling": {
            **handling,
            "audio_retention_days": (
                assembly.audio_retention_days
                if assembly.audio_retention_days is not None
                else handling.get("audio_retention_days", 0)
            ),
        },
        "table_number": recorder_session.table_number,
        # The organizer has asked the phones to delete their local copies. The
        # server cannot push, so it rides on this poll — which every recorder
        # already makes every few seconds.
        "purge_local_audio": assembly.device_audio_purge_requested_at is not None,
        "rounds": [
            {
                "id": round_.id,
                "position": round_.position,
                "title": round_.title,
                "question": round_.question,
                "duration_minutes": round_.duration_minutes,
                "status": round_.status,
                "recorded_state": recorded_rounds.get(round_.id),
                "table_summary": table_summaries.get(round_.id, ""),
            }
            for round_ in assembly.rounds
        ],
    }


def _report_available(
    session: Session, assembly: Assembly, analysis_enabled: bool | None = None
) -> bool:
    """Published explicitly — or, for independent assemblies, every table has
    completed every round (the organizer may still publish earlier)."""
    if assembly.report_published_at is not None:
        return True
    if assembly.recording_mode != "independent":
        return False
    # a closed session with a frozen report stays readable through a reopen
    if assembly.final_report_json:
        return True
    return rec_svc.assembly_complete(session, assembly, analysis_enabled)
