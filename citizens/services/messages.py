# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organizer → tables messages: "5 minutes left", "wrap up", a prompt (0.7).

The server cannot push to a phone; a message rides the status poll every
recorder already makes, and the phone reports the newest id it has shown.
Nothing here interrupts capture — the phone shows a banner, that is all.

Presets are rendered server-side in the assembly's language so an Italian
table reads "5 minuti rimasti" whatever language the organizer's screen is in.
"""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from citizens.db.models import RecorderSession, Round, SessionMessage
from citizens.db.models.base import utcnow
from citizens.db.models.messages import MESSAGE_KINDS
from citizens.services.audit import record_audit_event

MAX_TEXT = 300
# a phone with no receipt yet (just joined, or an older build) is shown only
# what is recent: a "10 minutes left" from an hour ago would mislead
FRESH_WINDOW = timedelta(minutes=10)
# how many a phone is handed at once; the newest wins the banner anyway
MAX_UNSEEN = 5

_PRESETS = {
    "en": {
        "TIME_LEFT": "{minutes} minutes left",
        "TIME_LEFT_ONE": "1 minute left",
        "WRAP_UP": "Please wrap up — bring the discussion to a close",
    },
    "it": {
        "TIME_LEFT": "{minutes} minuti rimasti",
        "TIME_LEFT_ONE": "1 minuto rimasto",
        "WRAP_UP": "Concludete — portate la discussione a una chiusura",
    },
}


def preset_text(language: str | None, kind: str, minutes: int | None) -> str:
    strings = _PRESETS.get((language or "en").split("-")[0].lower(), _PRESETS["en"])
    if kind == "TIME_LEFT":
        if minutes == 1:
            return strings["TIME_LEFT_ONE"]
        return strings["TIME_LEFT"].format(minutes=minutes)
    return strings["WRAP_UP"]


def post_message(
    session: Session,
    round_: Round,
    *,
    actor: str | None,
    kind: str,
    text: str | None = None,
    minutes: int | None = None,
    target_table_number: int | None = None,
    sound: bool = False,
) -> SessionMessage:
    if kind not in MESSAGE_KINDS:
        raise HTTPException(status_code=422, detail="Unknown message kind")
    if kind == "TIME_LEFT":
        if minutes is None or minutes < 1:
            raise HTTPException(status_code=422, detail="TIME_LEFT needs minutes")
        rendered = preset_text(round_.assembly.language, kind, minutes)
    elif kind == "WRAP_UP":
        rendered = preset_text(round_.assembly.language, kind, None)
    else:
        rendered = (text or "").strip()
        if not rendered:
            raise HTTPException(status_code=422, detail="A message needs text")
    if len(rendered) > MAX_TEXT:
        raise HTTPException(status_code=422, detail=f"Messages are at most {MAX_TEXT} characters")
    if target_table_number is not None and not any(
        t.number == target_table_number for t in round_.tables
    ):
        raise HTTPException(status_code=404, detail="No such table in this session")
    message = SessionMessage(
        assembly_id=round_.assembly_id,
        round_id=round_.id,
        created_by=actor,
        kind=kind,
        text=rendered,
        target_table_number=target_table_number,
        sound=sound,
    )
    session.add(message)
    session.flush()
    record_audit_event(
        session, "message_sent", "round", round_.id, actor=actor,
        data={"message_id": message.id, "kind": kind, "table": target_table_number, "chars": len(rendered)},
    )
    return message


def unseen_for(session: Session, recorder_session: RecorderSession) -> list[dict]:
    return unseen_for_table(
        session, recorder_session.assembly_id, recorder_session.table_number,
        recorder_session.last_seen_message_id,
    )


def unseen_for_table(
    session: Session, assembly_id: str, table_number: int, last_seen_message_id: int | None
) -> list[dict]:
    """What a phone at this table has not shown yet: the active session's
    messages for every table or for this one, above the phone's receipt (or,
    without a receipt, from the last few minutes). A facilitator's phone
    beside the table reads the same list with its own receipt."""
    query = (
        select(SessionMessage)
        .join(Round, Round.id == SessionMessage.round_id)
        .where(
            SessionMessage.assembly_id == assembly_id,
            Round.status == "ACTIVE",
            (SessionMessage.target_table_number.is_(None))
            | (SessionMessage.target_table_number == table_number),
        )
    )
    if last_seen_message_id is not None:
        query = query.where(SessionMessage.id > last_seen_message_id)
    else:
        query = query.where(SessionMessage.created_at >= utcnow() - FRESH_WINDOW)
    rows = session.execute(query.order_by(SessionMessage.id.desc()).limit(MAX_UNSEEN)).scalars()
    return [as_phone_dict(m) for m in reversed(list(rows))]


def mark_seen(session: Session, recorder_session, message_id: int) -> None:
    """The phone's receipt: never moves backwards, never beyond its own event.
    `recorder_session` is any row with `assembly_id` and
    `last_seen_message_id` — a recorder's or a facilitator's."""
    exists = session.execute(
        select(func.count()).where(
            SessionMessage.id == message_id,
            SessionMessage.assembly_id == recorder_session.assembly_id,
        )
    ).scalar_one()
    if not exists:
        raise HTTPException(status_code=404, detail="No such message")
    if (recorder_session.last_seen_message_id or 0) < message_id:
        recorder_session.last_seen_message_id = message_id


def author_of(created_by: str | None) -> str:
    """Who is speaking, for the phone's banner: the organizer (a user), the
    table's facilitator ("facilitator:<id>") or the AI facilitator ("ai")."""
    if created_by == "ai" or (created_by or "").startswith("ai:"):
        return "ai"
    if (created_by or "").startswith("facilitator:"):
        return "facilitator"
    return "organizer"


def as_phone_dict(message: SessionMessage) -> dict:
    return {
        "id": message.id,
        "kind": message.kind,
        "text": message.text,
        "sound": message.sound,
        "created_at": message.created_at,
        "author": author_of(message.created_by),
    }


def list_with_delivery(session: Session, round_: Round, limit: int = 20) -> list[dict]:
    """The session's newest messages, each with which tables have shown it.
    A table counts as reached when any of its recorder phones (not revoked)
    reports a receipt at or above the message."""
    messages = list(
        session.execute(
            select(SessionMessage)
            .where(SessionMessage.round_id == round_.id)
            .order_by(SessionMessage.id.desc())
            .limit(limit)
        ).scalars()
    )
    receipts: dict[int, int] = {}
    for table_number, seen in session.execute(
        select(RecorderSession.table_number, func.max(RecorderSession.last_seen_message_id))
        .where(
            RecorderSession.assembly_id == round_.assembly_id,
            RecorderSession.revoked_at.is_(None),
        )
        .group_by(RecorderSession.table_number)
    ):
        receipts[table_number] = seen or 0
    table_numbers = sorted(t.number for t in round_.tables)
    out = []
    for message in messages:
        targets = (
            [message.target_table_number]
            if message.target_table_number is not None
            else table_numbers
        )
        seen_by = [n for n in targets if receipts.get(n, 0) >= message.id]
        out.append(
            {
                **as_phone_dict(message),
                "target_table_number": message.target_table_number,
                "created_by": message.created_by,
                "author": author_of(message.created_by),
                "seen_by": seen_by,
                "not_seen_by": [n for n in targets if n not in seen_by],
            }
        )
    return out
