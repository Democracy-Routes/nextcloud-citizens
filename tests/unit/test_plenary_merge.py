# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Merging the room's overlapping device transcripts into one.

Several phones capture the same discussion from different spots. Naively
concatenating them counts each statement once per phone — the exact artifact a
multi-mic recording produces. The merge aligns them on the server clock and
drops near-duplicate utterances, keeping what only one device caught.
"""

from datetime import timedelta
from types import SimpleNamespace

from citizens.db.models.base import utcnow
from citizens.services.analysis import merge_plenary_segments


def _seg(seg_id, seq, start, end, text, speaker="SPEAKER_01"):
    return SimpleNamespace(
        id=seg_id, sequence=seq, start_seconds=start, end_seconds=end,
        text=text, speaker_label=speaker,
    )


def _device(recording_id, started_at, segments):
    recording = SimpleNamespace(id=recording_id, started_at=started_at)
    transcript = SimpleNamespace(recording_id=recording_id, segments=segments)
    return recording, transcript


def _merge(*devices):
    recordings = [d[0] for d in devices]
    transcripts = [d[1] for d in devices]
    return merge_plenary_segments(recordings, transcripts)


BASE = utcnow()


def test_the_same_utterance_heard_by_two_devices_is_kept_once():
    # both phones started together and heard the same sentence ~same time
    a = _device("A", BASE, [_seg("a0", 0, 2.0, 5.0, "we need later evening buses")])
    b = _device("B", BASE, [_seg("b0", 0, 2.3, 5.2, "we need later evening buses too")])

    merged = _merge(a, b)

    assert len(merged) == 1, "the duplicate should have been dropped"


def test_a_line_only_one_device_caught_survives():
    a = _device("A", BASE, [_seg("a0", 0, 2.0, 5.0, "we need later evening buses")])
    b = _device("B", BASE, [
        _seg("b0", 0, 2.2, 5.0, "we need later evening buses"),
        _seg("b1", 1, 8.0, 11.0, "and safer cycle lanes near the school"),
    ])

    merged = _merge(a, b)
    texts = [m["text"] for m in merged]

    assert any("cycle lanes" in t for t in texts), "unique line from B was lost"
    assert len([t for t in texts if "later evening buses" in t]) == 1


def test_dedupe_keeps_the_longer_cleaner_copy_and_its_ids():
    # two ASR variants of the same line; B's is a little fuller
    a = _device("A", BASE, [_seg("a0", 0, 2.0, 5.0, "we need later evening buses")])
    b = _device("B", BASE, [_seg("b0", 0, 2.1, 5.0, "we need later evening buses please")])

    merged = _merge(a, b)

    assert len(merged) == 1
    assert merged[0]["text"] == "we need later evening buses please"
    assert "b0" in merged[0]["ids"]


def test_far_apart_in_time_is_not_deduped_even_if_similar():
    # the same phrase said at minute 1 and again at minute 20 is two real events
    a = _device("A", BASE, [_seg("a0", 0, 60.0, 63.0, "we need later evening buses")])
    b = _device("B", BASE, [_seg("b0", 0, 1200.0, 1203.0, "we need later evening buses")])

    merged = _merge(a, b)

    assert len(merged) == 2


def test_a_late_joining_device_still_aligns_on_the_server_clock():
    # device B started 3 minutes after A; both heard a line at the same wall time
    a = _device("A", BASE, [_seg("a0", 0, 200.0, 203.0, "we should plant more trees")])
    b = _device("B", BASE + timedelta(minutes=3), [_seg("b0", 0, 20.0, 23.0, "we should plant more trees")])
    # A: 200s in → wall = BASE+200s ; B started at BASE+180s, 20s in → wall = BASE+200s

    merged = _merge(a, b)

    assert len(merged) == 1, "server-clock alignment should recognise these as one"


def test_a_device_never_dedupes_against_itself():
    # one phone legitimately repeating a phrase must keep both
    a = _device("A", BASE, [
        _seg("a0", 0, 2.0, 4.0, "clean the river"),
        _seg("a1", 1, 10.0, 12.0, "clean the river"),  # >1.5s later, not coalesced
    ])

    merged = _merge(a)

    assert len(merged) == 2


def test_output_is_ordered_by_global_time():
    a = _device("A", BASE, [_seg("a0", 0, 30.0, 32.0, "second point about housing")])
    b = _device("B", BASE, [_seg("b0", 0, 5.0, 7.0, "first point about transport")])

    merged = _merge(a, b)

    assert merged[0]["text"].startswith("first")
    assert merged[1]["text"].startswith("second")
