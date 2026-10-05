# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Round lifecycle + live table monitoring for the facilitator dashboard."""

import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import RecorderSession, Recording, Round
from citizens.db.models.base import utcnow
from citizens.domain.tables import color_for
from citizens.logging_setup import get_logger
from citizens.services import consent as consent_svc
from citizens.services import help as help_svc
from citizens.services import job_failures, readiness
from citizens.services.live_captions import LIVE_CAPTIONS
from citizens.services.provider_config import live_stt_snapshot
from citizens.services.table_recordings import slot_label

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


def _table_recorders(
    session: Session, round_: Round, table, recordings: list[Recording], now
) -> list[dict]:
    """One entry per recorder slot at the table: the newest phone in that slot,
    its liveness, and its newest recording of this round."""
    sessions = list(
        session.execute(
            select(RecorderSession)
            .where(
                RecorderSession.assembly_id == round_.assembly_id,
                RecorderSession.table_number == table.number,
            )
            .order_by(RecorderSession.slot, RecorderSession.created_at.desc())
        ).scalars()
    )
    newest_by_slot: dict[int, RecorderSession] = {}
    for recorder_session in sessions:
        newest_by_slot.setdefault(recorder_session.slot, recorder_session)
    slot_of_session = {s.id: s.slot for s in sessions}
    recording_by_slot: dict[int, Recording] = {}
    for recording in recordings:  # newest first
        slot = slot_of_session.get(recording.recorder_session_id or "", 1)
        recording_by_slot.setdefault(slot, recording)
    recorders = []
    for slot, recorder_session in sorted(newest_by_slot.items()):
        age = (
            (now - recorder_session.last_status_at).total_seconds()
            if recorder_session.last_status_at is not None
            else None
        )
        recording = recording_by_slot.get(slot)
        recorders.append(
            {
                "slot": slot,
                "label": slot_label(slot),
                "connected": age is not None and age < STALE_HEARTBEAT_SECONDS,
                "seconds_since_contact": int(age) if age is not None else None,
                "status": json.loads(recorder_session.last_status_json or "{}"),
                "recording": None
                if recording is None
                else {
                    "id": recording.id,
                    "state": recording.state,
                    # whether this recorder feeds the table's live captions
                    "live_source": recording.live_source,
                },
            }
        )
    return recorders


def round_monitor(session: Session, round_: Round) -> dict:
    """Per-table live health, combining device heartbeats with recording rows.

    'Local recording safe' is only claimed from a RECENT device-reported
    heartbeat with storage_ok (brief §25).
    """
    now = utcnow()
    # from the in-memory snapshot, never an OCS read inside this read session
    live_stt_enabled = bool(live_stt_snapshot().get("enabled"))
    # tables that raised their hand (services/help.py), by number
    hands = help_svc.open_by_table(session, round_.assembly_id)
    # who registered and consented at each table (services/consent.py); a
    # table nobody registered at reads as zero under the assembly's rule
    consents = consent_svc.consent_by_table(session, round_.assembly)
    consent_required = round_.assembly.participant_consent == "required"
    tables = []
    for table in round_.tables:
        consent = consents.get(table.number) or {
            "mode": round_.assembly.participant_consent, "registered": 0, "consenting": 0,
            "can_record": not consent_required,
        }
        recordings = list(
            session.execute(
                select(Recording)
                .where(Recording.round_id == round_.id, Recording.table_id == table.id)
                .order_by(Recording.created_at.desc())
            ).scalars()
        )
        recording = recordings[0] if recordings else None
        jobs = job_failures.jobs_for_recordings(session, recordings)
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
        recorders = _table_recorders(session, round_, table, recordings, now)
        live_source_slot = next(
            (r["slot"] for r in recorders if r["recording"] and r["recording"]["live_source"]), None
        )
        live_source_recording = next(
            (r["recording"]["id"] for r in recorders if r["slot"] == live_source_slot), None
        )
        # machine-readable "can this table record": status plus reason codes,
        # for an exception-first UI and an organizer's autopilot
        readiness_ = readiness.table_readiness(
            recorders,
            live_stt_enabled=live_stt_enabled,
            live_source_slot=live_source_slot,
            live_caption_reason=(
                LIVE_CAPTIONS.status(live_source_recording).get("reason")
                if live_source_recording
                else None
            ),
            round_active=round_.status == "ACTIVE",
            help_requested=(hands.get(table.number) or {}).get("kind"),
            consent_missing=not consent["can_record"],
        )

        tables.append(
            {
                "table_id": table.id,
                "number": table.number,
                "color_key": table.color_key or color_for(table.number),
                # the table's open request for the organizer, if its hand is up
                "help_request": hands.get(table.number),
                # registered / consenting people at this table, and whether the
                # assembly's consent rule lets it record
                "consent": consent,
                "device": device,
                "armed": armed,
                "local_recording_safe": local_safe,
                # every recorder of the table, one entry per slot (A, B, …):
                # `device` and `recording` above keep describing the newest
                # phone and the newest recording, as they always did
                "recorders": recorders,
                # which recorder's captions the room reads (None: no live source)
                "live_source_slot": live_source_slot,
                "readiness": readiness_.as_dict(),
                "recording": None
                if recording is None
                else {
                    "id": recording.id,
                    "state": recording.state,
                    "started_at": recording.started_at,
                    "received_chunks": recording.received_chunks,
                    "total_chunks": recording.total_chunks,
                    "error_code": recording.error_code,
                    "job": jobs.get(recording.id),
                },
                "superseded_recordings": [
                    {
                        "id": other.id,
                        "state": other.state,
                        "error_code": other.error_code,
                        "received_chunks": other.received_chunks,
                        "job": jobs.get(other.id),
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
        # READY / NEEDS_ATTENTION / BLOCKED counts and the worst of them
        "readiness": readiness.summarize(tables),
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
