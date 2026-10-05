# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One table, several recordings: told apart by time, named by slot."""

from datetime import timedelta
from types import SimpleNamespace

from citizens.db.models.base import utcnow
from citizens.services.files import audio_filename
from citizens.services.table_recordings import recordings_overlap, slot_label

T0 = utcnow()


def _rec(start, end, **extra):
    return SimpleNamespace(
        started_at=T0 + timedelta(seconds=start) if start is not None else None,
        ended_at=T0 + timedelta(seconds=end) if end is not None else None,
        updated_at=T0 + timedelta(seconds=end) if end is not None else None,
        **extra,
    )


def test_recorders_running_side_by_side_overlap():
    assert recordings_overlap([_rec(0, 1800), _rec(5, 1790)])


def test_a_replacement_or_record_the_rest_follows_and_does_not_overlap():
    assert not recordings_overlap([_rec(0, 600), _rec(610, 1800)])


def test_a_recording_that_never_completed_ends_at_its_last_chunk():
    stalled = SimpleNamespace(
        started_at=T0, ended_at=None, updated_at=T0 + timedelta(seconds=300)
    )
    # the replacement started two minutes after the last chunk: sequential
    assert not recordings_overlap([stalled, _rec(420, 1800)])
    # a second recorder that started while chunks were still arriving: side by side
    assert recordings_overlap([stalled, _rec(100, 1800)])


def test_unknown_spans_are_read_as_sequential():
    # concatenating is the safe reading: merging would drop lines as duplicates
    assert not recordings_overlap([_rec(None, None), _rec(0, 100)])
    assert not recordings_overlap([_rec(0, 100)])
    assert not recordings_overlap([])


def test_slot_labels_are_letters():
    assert [slot_label(n) for n in (1, 2, 3, 26, 27, 28)] == ["A", "B", "C", "Z", "AA", "AB"]
    assert slot_label(0) == "A"


def test_export_names_tell_the_recorders_apart():
    assembly = SimpleNamespace(name="Milan Mobility")
    recording = SimpleNamespace(
        table_number=7, canonical_audio_path="assembled/a/r.webm", superseded_at=None, id="rid"
    )
    assert audio_filename(assembly, recording, 1) == "Milan-Mobility-round1-table7-rid.webm"
    assert audio_filename(assembly, recording, 1, slot=2) == (
        "Milan-Mobility-round1-table7-recorderB-rid.webm"
    )
    recording.superseded_at = T0
    assert audio_filename(assembly, recording, 1, slot=1) == (
        "Milan-Mobility-round1-table7-part1-rid.webm"
    )
