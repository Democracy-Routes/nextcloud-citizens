# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A table is one discussion; its recordings are however many phones caught it.

    Session (round)
    └── Table
        ├── Recording A   slot 1, the table's own phone
        ├── Recording B   slot 2, a second recorder added by QR
        └── Recording C   slot 1 again — the first phone was replaced

Nothing may assume one table is one recording. Two shapes occur and are told
apart by TIME, not by how the recording came to exist:

- recordings that OVERLAP were made side by side (two recorders of one table,
  or a plenary room's phones) and hold the same words from different spots —
  the analysis merges and dedupes them (`analysis.merge_plenary_segments`);
- recordings that FOLLOW one another are one discussion with an interruption
  (a phone replaced, "record the rest of the round") — the analysis
  concatenates them with a marker at the join.

Both keep every recording: nothing here mixes audio or drops one.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import RecorderSession, Recording


def recordings_for_table(session: Session, round_id: str, table_id: str) -> list[Recording]:
    """Every recording of one table's discussion in one round, oldest first."""
    return list(
        session.execute(
            select(Recording)
            .where(Recording.round_id == round_id, Recording.table_id == table_id)
            .order_by(Recording.created_at)
        ).scalars()
    )


def recording_slots(session: Session, recordings: list[Recording]) -> dict[str, int]:
    """recording id → the recorder slot of the phone that made it (1 when the
    session is gone or predates slots)."""
    session_ids = [r.recorder_session_id for r in recordings if r.recorder_session_id]
    if not session_ids:
        return {r.id: 1 for r in recordings}
    slots = dict(
        session.execute(
            select(RecorderSession.id, RecorderSession.slot).where(
                RecorderSession.id.in_(session_ids)
            )
        ).all()
    )
    return {r.id: slots.get(r.recorder_session_id or "", 1) for r in recordings}


def slot_label(slot: int) -> str:
    """Slot 1 is Recorder A, 2 is B … 27 is AA; what the screens print."""
    label = ""
    n = max(slot, 1)
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        label = chr(ord("A") + remainder) + label
    return label


def _span(recording: Recording):
    """When the recording was being made, as far as the server can tell:
    from /start to /complete, or to the last chunk if it never completed."""
    if recording.started_at is None:
        return None
    end = recording.ended_at or recording.updated_at
    if end is None or end < recording.started_at:
        return None
    return recording.started_at, end


def recordings_overlap(recordings: list[Recording]) -> bool:
    """Were any two of these being made at the same time?

    Side-by-side recorders overlap for most of the round; a replacement or a
    "record the rest" starts after its predecessor stopped. A recording whose
    span is unknown is taken as sequential — concatenating is the safe
    reading, since merging would drop lines as duplicates.
    """
    spans = [span for span in (_span(r) for r in recordings) if span is not None]
    for index, (start_a, end_a) in enumerate(spans):
        for start_b, end_b in spans[index + 1:]:
            if start_a < end_b and start_b < end_a:
                return True
    return False
