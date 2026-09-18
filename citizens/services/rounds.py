# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Round lifecycle + live table monitoring for the facilitator dashboard."""

import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import RecorderSession, Recording, Round
from citizens.db.models.base import utcnow
from citizens.logging_setup import get_logger

log = get_logger(__name__)

STALE_HEARTBEAT_SECONDS = 45


def start_round(session: Session, round_: Round) -> Round:
    # A closed assembly is over: starting another round on it is what let a
    # facilitator who ended things early accidentally push every phone into
    # round 2. Reopen first if the assembly is genuinely resuming.
    if round_.assembly.closed_at is not None:
        raise HTTPException(status_code=409, detail="This assembly has been closed")
    if round_.status not in ("NOT_STARTED", "ENDED"):
        raise HTTPException(status_code=409, detail=f"Round is {round_.status}")
    other_active = [
        r for r in round_.assembly.rounds if r.status == "ACTIVE" and r.id != round_.id
    ]
    if other_active:
        raise HTTPException(status_code=409, detail="Another round is already active")
    # A restart runs from NOW. Keeping the original started_at made a
    # restarted round instantly "overrunning": the countdown counted up from
    # a start half an hour past, and the Live tab's grace window ended the
    # round the facilitator had just restarted within seconds.
    restarted = round_.status == "ENDED"
    round_.status = "ACTIVE"
    round_.started_at = utcnow() if restarted or round_.started_at is None else round_.started_at
    if restarted:
        round_.ended_at = None
    if round_.assembly.status in ("DRAFT", "READY"):
        round_.assembly.status = "ACTIVE"
    session.flush()
    log.info("round_started", round_id=round_.id, assembly_id=round_.assembly_id)
    return round_


def end_round(session: Session, round_: Round) -> Round:
    if round_.status != "ACTIVE":
        raise HTTPException(status_code=409, detail=f"Round is {round_.status}")
    round_.status = "ENDED"
    round_.ended_at = utcnow()
    session.flush()
    log.info("round_ended", round_id=round_.id, assembly_id=round_.assembly_id)
    return round_


def round_monitor(session: Session, round_: Round) -> dict:
    """Per-table live health, combining device heartbeats with recording rows.

    'Local recording safe' is only claimed from a RECENT device-reported
    heartbeat with storage_ok (brief §25).
    """
    now = utcnow()
    tables = []
    for table in round_.tables:
        recordings = list(
            session.execute(
                select(Recording)
                .where(Recording.round_id == round_.id, Recording.table_id == table.id)
                .order_by(Recording.created_at.desc())
            ).scalars()
        )
        recording = recordings[0] if recordings else None
        # A table whose phone was replaced has an earlier recording still on
        # its way to a transcript. Showing only the newest made the half we had
        # just salvaged vanish from the Live tab the moment the replacement
        # started, so a facilitator could not watch it finish.
        superseded = [other for other in recordings[1:] if other.superseded_at is not None]

        recorder_session = session.execute(
            select(RecorderSession)
            .where(
                RecorderSession.assembly_id == round_.assembly_id,
                RecorderSession.table_number == table.number,
                RecorderSession.revoked_at.is_(None),
            )
            .order_by(RecorderSession.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        device: dict = {"connected": False, "seconds_since_contact": None, "status": {}}
        if recorder_session is not None and recorder_session.last_status_at is not None:
            age = (now - recorder_session.last_status_at).total_seconds()
            device = {
                "connected": age < STALE_HEARTBEAT_SECONDS,
                "seconds_since_contact": int(age),
                "status": json.loads(recorder_session.last_status_json or "{}"),
            }
        local_safe = bool(
            device["connected"] and device["status"].get("storage_ok") is True
        )
        armed = bool(device["connected"] and device["status"].get("armed") is True)

        tables.append(
            {
                "table_id": table.id,
                "number": table.number,
                "device": device,
                "armed": armed,
                "local_recording_safe": local_safe,
                "recording": None
                if recording is None
                else {
                    "id": recording.id,
                    "state": recording.state,
                    "started_at": recording.started_at,
                    "received_chunks": recording.received_chunks,
                    "total_chunks": recording.total_chunks,
                    "error_code": recording.error_code,
                },
                "superseded_recordings": [
                    {
                        "id": other.id,
                        "state": other.state,
                        "error_code": other.error_code,
                        "received_chunks": other.received_chunks,
                    }
                    for other in superseded
                ],
            }
        )
    return {
        "round_id": round_.id,
        "status": round_.status,
        "started_at": round_.started_at,
        "duration_minutes": round_.duration_minutes,
        "recording_mode": round_.assembly.recording_mode,
        "tables_ready": sum(1 for t in tables if t["armed"]),
        "tables_total": len(tables),
        "tables": tables,
        # Every round's status, not just this one's. The Live tab polls this
        # every few seconds but computed "which round is next" from the
        # assembly it was handed on mount, which nothing refreshed — so it
        # could offer to start a round the server had already started, or hide
        # one that was available. One poll now answers both questions.
        "rounds": [
            {
                "id": other.id,
                "position": other.position,
                "title": other.title,
                "status": other.status,
            }
            for other in sorted(round_.assembly.rounds, key=lambda r: r.position)
        ],
    }
