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
  source passes to a sibling still recording, if there is one.

All of it runs inside the caller's write transaction, which already holds
SQLite's single writer slot, so two promotions at once are serialised and the
second simply sees the first.
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import Recording
from citizens.logging_setup import get_logger

log = get_logger(__name__)


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
        holder.live_source = False
        # the unique index wants the old flag gone before the new one is written
        session.flush()
    recording.live_source = True
    session.flush()
    log.info(
        "live_source_promoted",
        recording_id=recording.id, table_number=recording.table_number,
        from_recording_id=holder.id if holder is not None else None,
    )
    return holder
