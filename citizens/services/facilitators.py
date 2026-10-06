# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The facilitator's own phone beside a table (0.7).

A table's phone shows an "Add facilitator" code (FACILITATE_TABLE,
services/capabilities.py). The facilitator scans it with their own phone and
is handed a bearer for a view of ONE table: the session's question and
objective, the time left, who registered and consented, the table's hand,
the organizer's messages — and what the facilitator can do from there: write
a prompt to the table's phones, raise the table's hand, show a registration
code to register for consent, or turn this phone into a second recorder.

It never records, never joins a recorder slot, never sees another table. The
AI facilitator (services/facilitator.py) delivers its advice here first when
a facilitator's phone is connected, and to the table's phones only when none
is. Tokens are never logged; the session id is.
"""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import Assembly, FacilitatorSession, RecorderInvite, Round
from citizens.db.models.base import utcnow
from citizens.domain.tables import color_for
from citizens.logging_setup import get_logger
from citizens.security.recorder_tokens import generate_token, hash_token
from citizens.services import capabilities as capabilities_svc
from citizens.services import consent as consent_svc
from citizens.services import help as help_svc
from citizens.services import invites as invite_svc
from citizens.services import messages as messages_svc
from citizens.services.audit import record_audit_event

log = get_logger(__name__)

#: a facilitator's page lasts the day, not the week
SESSION_LIFETIME = timedelta(hours=12)
#: a facilitator phone that polled this recently counts as connected — the AI
#: facilitator addresses it instead of the table's phones
CONNECTED_WINDOW = timedelta(seconds=90)
#: the codes a facilitator may make: register for consent, add this phone (or
#: another) as a recorder of the table
CODE_PURPOSES = (capabilities_svc.REGISTER_PARTICIPANT, capabilities_svc.ADD_RECORDER_TO_TABLE)


def facilitation_code(session: Session, token: str) -> tuple[RecorderInvite, Assembly]:
    """The FACILITATE_TABLE code behind a token, or 401/409."""
    invite = invite_svc.find_by_token(session, token)
    if invite is None or invite.revoked_at is not None or invite_svc.is_expired(invite):
        raise HTTPException(status_code=401, detail="Invalid or expired facilitator code")
    if invite.purpose != capabilities_svc.FACILITATE_TABLE or invite.table_number is None:
        raise HTTPException(status_code=409, detail="This code does not add a facilitator")
    assembly = session.get(Assembly, invite.assembly_id)
    if assembly is None:
        raise HTTPException(status_code=404, detail="Assembly not found")
    if assembly.closed_at is not None:
        raise HTTPException(status_code=409, detail="This assembly has been closed by the organizer")
    return invite, assembly


def join(session: Session, token: str) -> tuple[FacilitatorSession, str, Assembly]:
    """A facilitator's phone redeems the table's code: a bearer for this
    table's view. The code stays valid — the same person may rescan after a
    reload, and a second facilitator at the table is not an error."""
    invite, assembly = facilitation_code(session, token)
    invite.last_used_at = utcnow()
    bearer = generate_token()
    facilitator = FacilitatorSession(
        assembly_id=assembly.id,
        table_number=invite.table_number,
        invite_id=invite.id,
        token_hash=hash_token(bearer),
        expires_at=utcnow() + SESSION_LIFETIME,
        last_seen_at=utcnow(),
    )
    session.add(facilitator)
    session.flush()
    record_audit_event(
        session, "facilitator_joined", "facilitator_session", facilitator.id,
        actor=f"facilitator:{facilitator.id}",
        data={"assembly_id": assembly.id, "table_number": facilitator.table_number,
              "invite_id": invite.id},
    )
    log.info(
        "facilitator_joined", facilitator_id=facilitator.id, assembly_id=assembly.id,
        table_number=facilitator.table_number,
    )
    return facilitator, bearer, assembly


def by_bearer(session: Session, bearer: str) -> FacilitatorSession:
    facilitator = session.execute(
        select(FacilitatorSession).where(FacilitatorSession.token_hash == hash_token(bearer))
    ).scalar_one_or_none()
    if (
        facilitator is None
        or facilitator.revoked_at is not None
        or facilitator.expires_at < utcnow()
    ):
        raise HTTPException(status_code=401, detail="Invalid or expired facilitator session")
    return facilitator


def touch(facilitator: FacilitatorSession) -> None:
    """The page's heartbeat: this phone is still beside the table."""
    facilitator.last_seen_at = utcnow()


def leave(session: Session, facilitator: FacilitatorSession) -> None:
    facilitator.revoked_at = utcnow()
    record_audit_event(
        session, "facilitator_left", "facilitator_session", facilitator.id,
        actor=f"facilitator:{facilitator.id}",
        data={"assembly_id": facilitator.assembly_id, "table_number": facilitator.table_number},
    )


def connected_for_table(
    session: Session, assembly_id: str, table_number: int
) -> FacilitatorSession | None:
    """The facilitator phone beside this table, if one polled recently."""
    return session.execute(
        select(FacilitatorSession)
        .where(
            FacilitatorSession.assembly_id == assembly_id,
            FacilitatorSession.table_number == table_number,
            FacilitatorSession.revoked_at.is_(None),
            FacilitatorSession.expires_at > utcnow(),
            FacilitatorSession.last_seen_at >= utcnow() - CONNECTED_WINDOW,
        )
        .order_by(FacilitatorSession.last_seen_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _current_round(assembly: Assembly) -> Round | None:
    """The session the facilitator is in: the active one, else the next one
    to come, else the last one that ran."""
    rounds = sorted(assembly.rounds, key=lambda r: r.position)
    for round_ in rounds:
        if round_.status == "ACTIVE":
            return round_
    for round_ in rounds:
        if round_.status == "NOT_STARTED":
            return round_
    return rounds[-1] if rounds else None


def _round_card(round_: Round | None) -> dict | None:
    if round_ is None:
        return None
    ends_at = None
    seconds_left = None
    if round_.status == "ACTIVE" and round_.started_at is not None:
        ends_at = round_.started_at + timedelta(minutes=round_.duration_minutes)
        seconds_left = int((ends_at - utcnow()).total_seconds())
    return {
        "id": round_.id,
        "position": round_.position,
        "title": round_.title,
        "question": round_.question,
        "objective": round_.objective or "",
        "status": round_.status,
        "duration_minutes": round_.duration_minutes,
        "started_at": round_.started_at,
        "ends_at": ends_at,
        # negative once the time is up: the page says "over by 3 min"
        "seconds_left": seconds_left,
    }


def status(session: Session, facilitator: FacilitatorSession) -> dict:
    """Everything the facilitator's page shows, for one table."""
    assembly = session.get(Assembly, facilitator.assembly_id)
    if assembly is None:
        raise HTTPException(status_code=404, detail="Assembly not found")
    table_number = facilitator.table_number
    roster = consent_svc.table_roster(session, assembly.id, table_number)
    return {
        "assembly": {
            "id": assembly.id,
            "kind": assembly.kind,
            "name": assembly.name,
            "language": assembly.language,
            "recording_mode": assembly.recording_mode,
        },
        "assembly_closed": assembly.closed_at is not None,
        "table_number": table_number,
        "color_key": color_for(table_number),
        "round": _round_card(_current_round(assembly)),
        "rounds": [
            {"id": r.id, "position": r.position, "title": r.title, "status": r.status}
            for r in sorted(assembly.rounds, key=lambda r: r.position)
        ],
        "consent": consent_svc.table_consent_state(session, assembly, table_number),
        "participants": roster,
        "recorders": capabilities_svc.recorder_count(session, assembly.id, table_number),
        "messages": messages_svc.unseen_for_table(
            session, assembly.id, table_number, facilitator.last_seen_message_id
        ),
        "help": help_svc.latest_for_table(session, assembly.id, table_number),
        # filled in by the AI facilitator and the live speaking metrics when
        # the engine provides them (phase C2/C3); explicit so the page can say
        # "not available with this engine" rather than show nothing
        "speaking": None,
        "advice": [],
        "capabilities": {"live_speaking_balance": False, "ai_facilitator": False},
    }


def send_prompt(session: Session, facilitator: FacilitatorSession, text: str) -> dict:
    """A prompt from the facilitator to this table's phones — the same banner
    the organizer's messages use, author "facilitator". Needs a session that
    is running: a prompt to a table that is not discussing has no reader."""
    assembly = session.get(Assembly, facilitator.assembly_id)
    if assembly is None:
        raise HTTPException(status_code=404, detail="Assembly not found")
    round_ = next((r for r in assembly.rounds if r.status == "ACTIVE"), None)
    if round_ is None:
        raise HTTPException(status_code=409, detail="No session is running at the moment")
    message = messages_svc.post_message(
        session, round_, actor=f"facilitator:{facilitator.id}", kind="PROMPT", text=text,
        target_table_number=facilitator.table_number, sound=True,
    )
    # the author has seen their own message
    if (facilitator.last_seen_message_id or 0) < message.id:
        facilitator.last_seen_message_id = message.id
    return messages_svc.as_phone_dict(message)


def raise_hand(session: Session, facilitator: FacilitatorSession, kind: str) -> dict:
    assembly = session.get(Assembly, facilitator.assembly_id)
    if assembly is None:
        raise HTTPException(status_code=404, detail="Assembly not found")
    if assembly.kind == "session":
        raise HTTPException(status_code=409, detail="A Session has no organizer to call")
    request = help_svc.raise_hand_at(
        session, assembly.id, facilitator.table_number, kind,
        actor=f"facilitator:{facilitator.id}",
    )
    return help_svc.as_dict(request)


def make_code(session: Session, facilitator: FacilitatorSession, purpose: str):
    """A code from the facilitator's phone: register for consent (shown to
    the facilitator themselves, or to a late arrival), or add a recorder to
    the table (this very phone, or another)."""
    if purpose not in CODE_PURPOSES:
        raise HTTPException(status_code=422, detail="Unknown capability")
    assembly = session.get(Assembly, facilitator.assembly_id)
    if assembly is None:
        raise HTTPException(status_code=404, detail="Assembly not found")
    round_ = next((r for r in assembly.rounds if r.status == "ACTIVE"), None)
    return capabilities_svc.mint_capability(
        session, assembly, purpose,
        table_number=facilitator.table_number,
        round_id=round_.id if round_ else None,
        actor=f"facilitator:{facilitator.id}",
    )
