# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Capabilities: what scanning a QR code lets a phone do, decided before the scan.

The phone that already joined chooses — "add a recorder to this table", "add a
new table" — and shows a code that means exactly that. The scanning phone
follows it; it never picks a role. Both are short-lived and single-use, so a
photographed screen cannot be replayed, and both are server-enforced: nothing
about them is trusted from the client.

They share the row, token mechanism and `#/join/<token>` route with the printed
table codes (`RecorderInvite`, services/invites.py) — hashing, vault, rate
limit, brute-force protection, revocation all come for free — and differ by
`purpose`:

  JOIN_TABLE             the printed table code; reusable (a replacement phone
                         rescans the poster); slot 1
  ADD_RECORDER_TO_TABLE  made at table N; the scanner joins table N in the
                         next recorder slot, recording beside the others
  ADD_TABLE              made in a Session; the next table is created in every
                         round and the scanner is its first recorder (slot 1)

A table's identity is its number, the same in every round, so ADD_TABLE's
`round_id` is the Session the code was made in — scope and audit — not a
restriction on where the table lives. A future stable physical-table code is
simply a JOIN_TABLE row with no round, which nothing here forecloses.

Tokens are never logged or written to the audit trail; the invite id is.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from citizens.db.models import Assembly, RecorderInvite, RecorderSession, Round
from citizens.db.models.base import utcnow
from citizens.domain.tables import color_for
from citizens.logging_setup import get_logger
from citizens.security.invite_vault import encrypt_token
from citizens.security.recorder_tokens import generate_token, hash_token
from citizens.services import invites as invite_svc
from citizens.services import recording as rec_svc
from citizens.services import tables as tables_svc
from citizens.services.audit import record_audit_event

log = get_logger(__name__)

JOIN_TABLE = invite_svc.JOIN_TABLE
ADD_RECORDER_TO_TABLE = "ADD_RECORDER_TO_TABLE"
ADD_TABLE = "ADD_TABLE"
#: The purposes a joined phone may make a code for.
ACTION_PURPOSES = (ADD_RECORDER_TO_TABLE, ADD_TABLE)

#: How long an action code stays scannable. Long enough to walk a phone across
#: the room; short enough that a photographed screen is useless by the break.
CAPABILITY_TTL = timedelta(minutes=15)


@dataclass(frozen=True)
class CapabilityCard:
    """What the phone shows: the intent, the code, and the table it concerns."""

    invite_id: str
    purpose: str
    url: str
    qr_svg: str
    expires_at: datetime
    table_number: int | None
    color_key: str | None
    round_id: str | None

    def as_dict(self) -> dict:
        return {
            "purpose": self.purpose,
            "url": self.url,
            "qr_svg": self.qr_svg,
            "expires_at": self.expires_at,
            "table_number": self.table_number,
            "color_key": self.color_key,
            "round_id": self.round_id,
        }


@dataclass(frozen=True)
class Joined:
    """A phone that redeemed a code: its session and what the code made it."""

    recorder_session: RecorderSession
    bearer: str
    purpose: str
    table_number: int
    color_key: str
    slot: int
    table_created: bool

    def as_dict(self) -> dict:
        return {
            "purpose": self.purpose,
            "table_number": self.table_number,
            "color_key": self.color_key,
            "slot": self.slot,
            "table_created": self.table_created,
        }


def create_capability(
    session: Session,
    recorder_session: RecorderSession,
    purpose: str,
    round_id: str | None = None,
) -> CapabilityCard:
    """A joined phone makes a code for the next phone. Server-checked throughout."""
    if purpose not in ACTION_PURPOSES:
        raise HTTPException(status_code=422, detail="Unknown capability")
    assembly = session.get(Assembly, recorder_session.assembly_id)
    if assembly is None:
        raise HTTPException(status_code=404, detail="Assembly not found")
    if assembly.closed_at is not None:
        raise HTTPException(status_code=409, detail="This assembly has been closed")
    if purpose == ADD_TABLE and assembly.recording_mode == "plenary":
        raise HTTPException(
            status_code=409, detail="A plenary room is one table; add phones to it instead"
        )
    if round_id is not None:
        round_ = session.get(Round, round_id)
        if round_ is None or round_.assembly_id != assembly.id:
            raise HTTPException(status_code=404, detail="Round not found")

    now = utcnow()
    token = generate_token()
    table_number = recorder_session.table_number if purpose == ADD_RECORDER_TO_TABLE else None
    invite = RecorderInvite(
        assembly_id=assembly.id,
        purpose=purpose,
        table_number=table_number,
        round_id=round_id,
        single_use=True,
        token_hash=hash_token(token),
        token_encrypted=encrypt_token(token),
        expires_at=now + CAPABILITY_TTL,
        created_by_session_id=recorder_session.id,
    )
    session.add(invite)
    session.flush()
    record_audit_event(
        session, "capability_created", "recorder_invite", invite.id,
        actor=f"recorder-session:{recorder_session.id}",
        data={
            "purpose": purpose,
            "assembly_id": assembly.id,
            "round_id": round_id,
            "table_number": table_number,
            "expires_at": invite.expires_at.isoformat(),
        },
    )
    log.info(
        "capability_created",
        invite_id=invite.id, purpose=purpose, assembly_id=assembly.id,
        table_number=table_number, by_session=recorder_session.id,
    )
    url = invite_svc.recorder_join_url(token)
    return CapabilityCard(
        invite_id=invite.id,
        purpose=purpose,
        url=url,
        qr_svg=invite_svc.qr_svg(url),
        expires_at=invite.expires_at,
        table_number=table_number,
        color_key=color_for(table_number) if table_number is not None else None,
        round_id=round_id,
    )


def join_with_token(session: Session, token: str) -> Joined:
    """Redeem whatever the token is: a table code, or an action code.

    The caller's write transaction already holds SQLite's single writer slot
    (BEGIN IMMEDIATE on the first statement), so two phones scanning one
    single-use code are serialised here; the conditional UPDATE on
    `consumed_at` is the belt to that brace, and the loser is told the code
    was already used rather than handed a second table.
    """
    invite = invite_svc.find_by_token(session, token)
    if invite is None or invite.revoked_at is not None or invite_svc.is_expired(invite):
        if invite is not None:
            log.info("capability_refused", invite_id=invite.id, purpose=invite.purpose,
                     reason="revoked" if invite.revoked_at is not None else "expired")
        raise HTTPException(status_code=401, detail="Invalid or revoked invite")

    if invite.purpose == JOIN_TABLE:
        if invite.table_number is None:
            raise HTTPException(status_code=409, detail="This code is not a table code")
        recorder_session, bearer = rec_svc.mint_session(session, invite, invite.table_number, slot=1)
        return Joined(
            recorder_session=recorder_session, bearer=bearer, purpose=JOIN_TABLE,
            table_number=invite.table_number, color_key=color_for(invite.table_number),
            slot=1, table_created=False,
        )

    if invite.single_use:
        claimed = session.execute(
            update(RecorderInvite)
            .where(RecorderInvite.id == invite.id, RecorderInvite.consumed_at.is_(None))
            .values(consumed_at=utcnow())
        )
        if claimed.rowcount == 0:
            log.info("capability_refused", invite_id=invite.id, purpose=invite.purpose,
                     reason="consumed")
            raise HTTPException(status_code=410, detail="This code has already been used")
        session.refresh(invite)

    assembly = session.get(Assembly, invite.assembly_id)
    if assembly is None:
        raise HTTPException(status_code=404, detail="Assembly not found")
    if assembly.closed_at is not None:
        raise HTTPException(status_code=409, detail="This assembly has been closed")

    if invite.purpose == ADD_RECORDER_TO_TABLE:
        if invite.table_number is None:
            raise HTTPException(status_code=409, detail="This code names no table")
        table_number = invite.table_number
        slot = next_slot(session, assembly.id, table_number)
        # the session points at the table's own code where one exists, so the
        # phone shows the room a code that still works after this one is spent
        join_invite = invite_svc.active_invite_for_table(session, assembly.id, table_number) or invite
        recorder_session, bearer = rec_svc.mint_session(session, join_invite, table_number, slot=slot)
        table_created = False
    elif invite.purpose == ADD_TABLE:
        added = tables_svc.add_table(
            session, assembly, actor=f"recorder-session:{invite.created_by_session_id}"
        )
        table_number, slot, table_created = added.number, 1, True
        join_invite = invite_svc.active_invite_for_table(session, assembly.id, table_number) or invite
        recorder_session, bearer = rec_svc.mint_session(session, join_invite, table_number, slot=1)
    else:
        raise HTTPException(status_code=409, detail="Unknown capability")

    record_audit_event(
        session, "capability_consumed", "recorder_invite", invite.id,
        actor=f"recorder-session:{recorder_session.id}",
        data={
            "purpose": invite.purpose,
            "assembly_id": assembly.id,
            "round_id": invite.round_id,
            "table_number": table_number,
            "slot": slot,
            "table_created": table_created,
            "made_by_session": invite.created_by_session_id,
        },
    )
    log.info(
        "capability_consumed",
        invite_id=invite.id, purpose=invite.purpose, assembly_id=assembly.id,
        table_number=table_number, slot=slot, table_created=table_created,
    )
    return Joined(
        recorder_session=recorder_session, bearer=bearer, purpose=invite.purpose,
        table_number=table_number, color_key=color_for(table_number),
        slot=slot, table_created=table_created,
    )


def peek(session: Session, token: str) -> dict:
    """What a code would do if scanned — read without consuming anything.

    The phone asks this before joining so it can warn about an accident (a
    third recorder at a table, a phone that was recording another table) and
    let the person cancel without spending a single-use code. Says only what
    the code's own screen already shows; a dead code is reported as such.
    """
    invite = invite_svc.find_by_token(session, token)
    if invite is None or invite.revoked_at is not None or invite_svc.is_expired(invite):
        return {"valid": False, "reason": "invalid"}
    if invite.single_use and invite.consumed_at is not None:
        return {"valid": False, "reason": "consumed"}
    table_number = invite.table_number
    recorders = (
        recorder_count(session, invite.assembly_id, table_number) if table_number is not None else 0
    )
    return {
        "valid": True,
        "purpose": invite.purpose,
        "table_number": table_number,
        "color_key": color_for(table_number) if table_number is not None else None,
        "recorders": recorders,
        "assembly_id": invite.assembly_id,
    }


def recorder_count(session: Session, assembly_id: str, table_number: int) -> int:
    """How many recorder slots a table has phones in (sessions not revoked)."""
    return int(
        session.execute(
            select(func.count(func.distinct(RecorderSession.slot))).where(
                RecorderSession.assembly_id == assembly_id,
                RecorderSession.table_number == table_number,
                RecorderSession.revoked_at.is_(None),
            )
        ).scalar_one()
        or 0
    )


def next_slot(session: Session, assembly_id: str, table_number: int) -> int:
    """The next recorder slot at a table. Slots are never reused — a revoked or
    expired recorder keeps its number, so recordings stay attributable."""
    highest = session.execute(
        select(func.max(RecorderSession.slot)).where(
            RecorderSession.assembly_id == assembly_id,
            RecorderSession.table_number == table_number,
        )
    ).scalar_one()
    return (highest or 0) + 1
