# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""How much each voice spoke in a round — an honest, single-device estimate.

Diarization gives us anonymous speaker labels ("who spoke", not "whom"), and
those labels are **only** consistent within one recording: SPEAKER_00 on one
phone is not SPEAKER_00 on another. So a round's speaking balance is computed
from the one recording that captured the most speech — a single coherent voice
set — rather than trying to reconcile labels across devices, which is
impossible from diarization alone. The result is deliberately anonymous: voices
are relabelled A, B, C… and never named.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import Recording, Round, Transcript, TranscriptSegment

# Above this many distinct voices the donut turns to mush, so the quietest are
# folded into a single "Others" slice.
MAX_VOICES = 6
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _percentages(seconds: list[float], total: float) -> list[int]:
    """Whole-number percentages that sum to exactly 100 (largest remainder)."""
    if total <= 0:
        return [0 for _ in seconds]
    raw = [s / total * 100 for s in seconds]
    floors = [int(x) for x in raw]
    shortfall = 100 - sum(floors)
    # hand the leftover points to the slices with the largest fractional part
    order = sorted(range(len(raw)), key=lambda i: raw[i] - floors[i], reverse=True)
    for i in order[: max(0, shortfall)]:
        floors[i] += 1
    return floors


def round_speaking_balance(session: Session, round_: Round) -> dict | None:
    """Talk-time share per detected voice, from the round's fullest recording.

    Returns ``{"voices": [{"label", "seconds", "percent"}], "total_seconds",
    "from_recording_id"}`` or ``None`` when the round has no transcribed speech
    to measure.
    """
    recordings = list(
        session.execute(
            select(Recording).where(Recording.round_id == round_.id)
        ).scalars()
    )
    if not recordings:
        return None

    # segments per recording, and the total speech each captured
    best_id: str | None = None
    best_total = 0.0
    best_segments: list[TranscriptSegment] = []
    for rec in recordings:
        segments = list(
            session.execute(
                select(TranscriptSegment)
                .join(Transcript, Transcript.id == TranscriptSegment.transcript_id)
                .where(Transcript.recording_id == rec.id)
            ).scalars()
        )
        total = sum(max(0.0, s.end_seconds - s.start_seconds) for s in segments)
        if total > best_total:
            best_total, best_id, best_segments = total, rec.id, segments

    if best_id is None or best_total <= 0:
        return None

    # sum talk-time per diarization label
    by_label: dict[str, float] = {}
    for seg in best_segments:
        dur = max(0.0, seg.end_seconds - seg.start_seconds)
        if dur <= 0:
            continue
        by_label[seg.speaker_label] = by_label.get(seg.speaker_label, 0.0) + dur

    ranked = sorted(by_label.values(), reverse=True)
    if not ranked:
        return None

    # keep the loudest MAX_VOICES, fold the rest into one "Others" slice
    head = ranked[:MAX_VOICES]
    tail = ranked[MAX_VOICES:]
    seconds = list(head)
    labels = [_LETTERS[i] for i in range(len(head))]
    if tail:
        seconds.append(sum(tail))
        labels.append("Others")

    percents = _percentages(seconds, sum(seconds))
    voices = [
        {"label": label, "seconds": round(sec, 1), "percent": pct}
        for label, sec, pct in zip(labels, seconds, percents, strict=True)
    ]
    return {
        "voices": voices,
        "total_seconds": round(best_total, 1),
        "from_recording_id": best_id,
    }
