# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A table raising its hand: Need help → the Live tab (0.7).

One open request per table: a second tap changes what the table is asking
for rather than stacking a queue nobody will read. The organizer
acknowledges from the Live tab; the phone learns that on its status poll
and says "the organizer has seen it". A recent, acknowledged request is
still reported to the phone for a short while so that sentence can be shown.
"""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import HelpRequest, RecorderSession, Round
from citizens.db.models.base import utcnow
from citizens.db.models.help import HELP_KINDS
from citizens.services.audit import record_audit_event

#: how long an acknowledged request keeps appearing on the phone's status
ACKNOWLEDGED_VISIBLE = timedelta(minutes=2)
#: an open request older than this is stale — the session moved on
OPEN_VISIBLE = timedelta(hours=3)


def raise_hand(session: Session, recorder_session: RecorderSession, kind: str) -> HelpRequest:
    if kind not in HELP_KINDS:
        raise HTTPException(status_code=422, detail="Unknown kind of help")
    active_round = session.execute(
        select(Round.id).where(
            Round.assembly_id == recorder_session.assembly_id, Round.status == "ACTIVE"
        )
    ).scalar_one_or_none()
    request = open_for_table(session, recorder_session.assembly_id, recorder_session.table_number)
    if request is not None:
        # the same table again: what it needs may have changed, not how many
        # times it needs it
        request.kind = kind
        request.slot = recorder_session.slot
        request.created_at = utcnow()
        request.round_id = active_round
    else:
        request = HelpRequest(
            assembly_id=recorder_session.assembly_id,
            round_id=active_round,
            table_number=recorder_session.table_number,
            slot=recorder_session.slot,
            kind=kind,
        )
        session.add(request)
        session.flush()
    record_audit_event(
        session, "help_requested", "help_request", request.id,
        data={"table": request.table_number, "slot": request.slot, "kind": kind},
    )
    return request


def open_for_table(session: Session, assembly_id: str, table_number: int) -> HelpRequest | None:
    return session.execute(
        select(HelpRequest)
        .where(
            HelpRequest.assembly_id == assembly_id,
            HelpRequest.table_number == table_number,
            HelpRequest.acknowledged_at.is_(None),
            HelpRequest.created_at >= utcnow() - OPEN_VISIBLE,
        )
        .order_by(HelpRequest.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def latest_for_phone(session: Session, recorder_session: RecorderSession) -> dict | None:
    """What the phone shows: its table's open request, or one acknowledged a
    moment ago (so "the organizer has seen it" can be said), else nothing."""
    request = session.execute(
        select(HelpRequest)
        .where(
            HelpRequest.assembly_id == recorder_session.assembly_id,
            HelpRequest.table_number == recorder_session.table_number,
        )
        .order_by(HelpRequest.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if request is None:
        return None
    now = utcnow()
    if request.acknowledged_at is None:
        if request.created_at < now - OPEN_VISIBLE:
            return None
    elif request.acknowledged_at < now - ACKNOWLEDGED_VISIBLE:
        return None
    return as_dict(request)


def open_by_table(session: Session, assembly_id: str) -> dict[int, dict]:
    """For the monitor: every table's open request, by table number."""
    rows = session.execute(
        select(HelpRequest)
        .where(
            HelpRequest.assembly_id == assembly_id,
            HelpRequest.acknowledged_at.is_(None),
            HelpRequest.created_at >= utcnow() - OPEN_VISIBLE,
        )
        .order_by(HelpRequest.created_at.asc())
    ).scalars()
    return {request.table_number: as_dict(request) for request in rows}


def acknowledge(session: Session, request: HelpRequest, actor: str) -> HelpRequest:
    if request.acknowledged_at is None:
        request.acknowledged_at = utcnow()
        request.acknowledged_by = actor
        record_audit_event(
            session, "help_acknowledged", "help_request", request.id, actor=actor,
            data={"table": request.table_number, "kind": request.kind},
        )
    return request


def as_dict(request: HelpRequest) -> dict:
    return {
        "id": request.id,
        "kind": request.kind,
        "table_number": request.table_number,
        "slot": request.slot,
        "created_at": request.created_at,
        "acknowledged_at": request.acknowledged_at,
    }
