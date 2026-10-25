# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Participants validate their table's published summary (0.7).

"Does this reflect your table's discussion?" — Looks right / Something is
missing, with a note. One answer per person and session; the organizer sees
counts and notes beside each table, the report counts them. A flag for a
human, never a vote and never an edit of the findings.
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import (
    Participant,
    ParticipantSession,
    Round,
    SummaryValidation,
    TableAssignment,
)
from citizens.db.models.validation import VERDICTS
from citizens.services.audit import record_audit_event

MAX_NOTE = 1000


def table_for(session: Session, participant: Participant, round_: Round) -> int | None:
    """Where the person sat in this round: the seating if there is one, else
    the table they registered at."""
    seated = session.execute(
        select(TableAssignment)
        .where(
            TableAssignment.round_id == round_.id,
            TableAssignment.participant_id == participant.id,
        )
        .limit(1)
    ).scalar_one_or_none()
    if seated is not None:
        return seated.table.number
    return participant.registered_table_number


def record(
    session: Session,
    participant_session: ParticipantSession,
    round_id: str,
    verdict: str,
    note: str = "",
) -> SummaryValidation:
    if verdict not in VERDICTS:
        raise HTTPException(status_code=422, detail="Unknown verdict")
    round_ = session.get(Round, round_id)
    if round_ is None or round_.assembly_id != participant_session.assembly_id:
        raise HTTPException(status_code=404, detail="Session not found")
    participant = session.get(Participant, participant_session.participant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    existing = session.execute(
        select(SummaryValidation).where(
            SummaryValidation.round_id == round_.id,
            SummaryValidation.participant_id == participant.id,
        )
    ).scalar_one_or_none()
    note = (note or "").strip()[:MAX_NOTE]
    if existing is not None:
        existing.verdict = verdict
        existing.note = note
        existing.table_number = table_for(session, participant, round_)
        validation = existing
    else:
        validation = SummaryValidation(
            assembly_id=participant_session.assembly_id,
            round_id=round_.id,
            participant_id=participant.id,
            table_number=table_for(session, participant, round_),
            verdict=verdict,
            note=note,
        )
        session.add(validation)
    session.flush()
    record_audit_event(
        session, "summary_validated", "round", round_.id,
        data={"table": validation.table_number, "verdict": verdict, "note_chars": len(note)},
    )
    return validation


def for_participant(session: Session, participant_id: str) -> dict[str, dict]:
    """What this person already answered, by round id."""
    rows = session.execute(
        select(SummaryValidation).where(SummaryValidation.participant_id == participant_id)
    ).scalars()
    return {v.round_id: {"verdict": v.verdict, "note": v.note} for v in rows}


def by_table(session: Session, assembly_id: str) -> dict[tuple[str, int | None], dict]:
    """Counts and notes per (round, table) for the organizer and the report."""
    out: dict[tuple[str, int | None], dict] = {}
    for v in session.execute(
        select(SummaryValidation)
        .where(SummaryValidation.assembly_id == assembly_id)
        .order_by(SummaryValidation.created_at)
    ).scalars():
        entry = out.setdefault((v.round_id, v.table_number), {"looks_right": 0, "missing": 0, "notes": []})
        if v.verdict == "LOOKS_RIGHT":
            entry["looks_right"] += 1
        else:
            entry["missing"] += 1
            if v.note:
                entry["notes"].append(v.note)
    return out


def counts(session: Session, assembly_id: str) -> dict:
    total = looks_right = 0
    for entry in by_table(session, assembly_id).values():
        looks_right += entry["looks_right"]
        total += entry["looks_right"] + entry["missing"]
    return {"answered": total, "looks_right": looks_right, "missing": total - looks_right}
