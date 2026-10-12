# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One live-caption source per table.

Several phones may record one table (services/table_recordings.py). All of
them upload, and every recording is transcribed afterwards — but only one
drives the live captions, or the room pays for N streaming sessions, reads N
competing caption feeds, and a future facilitator is handed two versions of
the same minute. `Recording.live_source` marks that one; a partial unique index
on (round, table) WHERE live_source makes a second primary impossible whatever
happens here.

Rules:
- the first recording to start at a table takes the source (so a table with
  one phone behaves exactly as before);
- a backup recorder uploads its audio but its chunks are not fed to the
  caption engine, and its phone is told whose captions it is watching;
- any recorder still recording can be promoted — by its own phone or the
  organizer — and the previous holder's caption session is ended;
- when the holder stops (completed, replaced, gone silent, timed out) the
  source passes to a sibling still recording, if there is one;
- when the holder's phone has sent no chunk for STALL_SECONDS while a sibling
  keeps sending, the sibling's next chunk takes the source (`take_over_if_stalled`),
  and takes it back the same way when the roles reverse. A phone in the
  background still "records" as far as its state goes, but the captions must
  follow the audio that actually arrives (the 2026-10-11 field test).

All of it runs inside the caller's write transaction, which already holds
SQLite's single writer slot, so two promotions at once are serialised and the
second simply sees the first.
"""

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from citizens.db.models import Recording
from citizens.db.models.base import utcnow
from citizens.logging_setup import get_logger
from citizens.services.audit import record_audit_event

log = get_logger(__name__)

#: A live source whose phone has sent nothing for this long, while a sibling's
#: chunks keep arriving, hands the captions to that sibling. Chunks come every
#: ~10 s, so this is three missed ones — the same bar as the Live tab's
#: CAPTURE_SILENT warning (services/readiness.py).
STALL_SECONDS = 30



def _demote(session: Session, holder: Recording) -> None:
    """Take the flag off the holder WITHOUT touching its clock. An ORM update
    bumps `updated_at` (the row's onupdate), and that column is the silence
    clock: the Live tab's CAPTURE_SILENT, the replacement phone's silent-device
    path and this module's own stall rule all read it. A failover must not
    make the phone that just fell silent look alive again."""
    session.execute(
        update(Recording)
        .where(Recording.id == holder.id)
        .values(live_source=False, updated_at=holder.updated_at)
    )
    holder.live_source = False
    session.expire(holder, ["live_source", "updated_at"])
    session.flush()


def current(session: Session, round_id: str, table_id: str) -> Recording | None:
    """The table's live source in this round, if any."""
    return session.execute(
        select(Recording).where(
            Recording.round_id == round_id,
            Recording.table_id == table_id,
            Recording.live_source.is_(True),
        )
    ).scalars().first()


def assign_if_vacant(session: Session, recording: Recording) -> bool:
    """A recording just started: take the source unless another recording of
    the table is still recording and holds it. Returns whether it took it."""
    holder = current(session, recording.round_id, recording.table_id)
    if holder is not None and holder.id != recording.id:
        if holder.state == "RECORDING":
            return False
        # a holder that stopped without passing the flag on (a row from before
        # every stop path released it): take over
        holder.live_source = False
        session.flush()
    recording.live_source = True
    session.flush()
    log.info(
        "live_source_assigned",
        recording_id=recording.id, round_id=recording.round_id, table_number=recording.table_number,
    )
    return True


def release(session: Session, recording: Recording) -> Recording | None:
    """This recording stopped being made: pass the source to a sibling that is
    still recording, or leave the table without one. Returns the successor."""
    if not recording.live_source:
        return None
    recording.live_source = False
    session.flush()
    successor = session.execute(
        select(Recording)
        .where(
            Recording.round_id == recording.round_id,
            Recording.table_id == recording.table_id,
            Recording.id != recording.id,
            Recording.state == "RECORDING",
            Recording.superseded_at.is_(None),
        )
        # the one that most recently sent audio is the one most surely alive
        .order_by(Recording.updated_at.desc())
    ).scalars().first()
    if successor is None:
        log.info("live_source_released", recording_id=recording.id,
                 table_number=recording.table_number)
        return None
    successor.live_source = True
    session.flush()
    log.info(
        "live_source_failover",
        from_recording_id=recording.id, to_recording_id=successor.id,
        table_number=recording.table_number,
    )
    return successor


def promote(session: Session, recording: Recording) -> Recording | None:
    """Make this recording the table's live source. Returns the recording it
    took the source from (so its caption session can be ended), or None."""
    if recording.state != "RECORDING":
        raise HTTPException(
            status_code=409, detail="Only a recording still in progress can carry live captions"
        )
    holder = current(session, recording.round_id, recording.table_id)
    if holder is not None and holder.id == recording.id:
        return None
    if holder is not None:
        # the unique index wants the old flag gone before the new one is written
        _demote(session, holder)
    recording.live_source = True
    session.flush()
    log.info(
        "live_source_promoted",
        recording_id=recording.id, table_number=recording.table_number,
        from_recording_id=holder.id if holder is not None else None,
    )
    return holder


def take_over_if_stalled(session: Session, recording: Recording, now=None) -> Recording | None:
    """A chunk just arrived from `recording`, a recorder that is NOT the table's
    live source. If the source's phone has been silent for STALL_SECONDS, this
    one takes the captions over; returns the recording it took them from, so
    the caller can end that caption session. None when nothing changed.

    `updated_at` bumps on every received chunk and is left alone by the flag
    flip (`_demote`), so the phone that fell silent still reads as silent to
    the Live tab and to a replacement phone; the new holder's own chunks keep
    its clock fresh, so the roles reverse only when it stalls in turn."""
    if recording.live_source or recording.state != "RECORDING":
        return None
    holder = current(session, recording.round_id, recording.table_id)
    if holder is None:
        # a table whose source stopped without a successor: this one is it
        assign_if_vacant(session, recording)
        return None
    if holder.id == recording.id:
        return None
    now = now or utcnow()
    silent = (now - holder.updated_at).total_seconds() if holder.updated_at is not None else 0
    if holder.state == "RECORDING" and silent < STALL_SECONDS:
        return None
    _demote(session, holder)  # the unique index wants the old flag gone first
    recording.live_source = True
    session.flush()
    log.warning(
        "live_source_failover",
        from_recording_id=holder.id, to_recording_id=recording.id,
        table_number=recording.table_number, reason="stall", silent_seconds=int(silent),
    )
    record_audit_event(
        session, "live_source_failover", "recording", recording.id,
        data={
            "from_recording_id": holder.id, "table_number": recording.table_number,
            "reason": "stall", "silent_seconds": int(silent),
        },
    )
    return holder
