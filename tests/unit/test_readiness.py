# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Is this table ready? Status plus reason codes, no prose, not every problem blocks."""

from citizens.services import readiness as r


def _recorder(slot=1, connected=True, state="RECORDING", live_source=False, **status):
    return {
        "slot": slot,
        "connected": connected,
        "seconds_since_contact": 5 if connected else 300,
        "status": status,
        "recording": {"id": f"rec-{slot}", "state": state, "live_source": live_source} if state else None,
    }


def _codes(result):
    return [(reason.code, reason.severity, reason.slot) for reason in result.reasons]


def test_one_healthy_recorder_with_no_backup_is_ready():
    result = r.table_readiness([_recorder(storage_ok=True, battery_level=0.8, capture_ok=True)])
    assert result.status == r.READY
    assert result.reasons == []


def test_a_raised_hand_keeps_a_healthy_table_in_view_without_blocking_it():
    healthy = _recorder(storage_ok=True, battery_level=0.8, capture_ok=True)
    result = r.table_readiness([healthy], help_requested="PROCESS")
    assert result.status == r.NEEDS_ATTENTION
    assert _codes(result) == [(r.HELP_REQUESTED, r.WARNING, None)]
    assert result.reasons[0].data == {"kind": "PROCESS"}
    # ...and rides along with a blocker rather than replacing it
    result = r.table_readiness([], help_requested="TECHNICAL")
    assert result.status == r.BLOCKED
    assert _codes(result) == [(r.NO_RECORDER, r.BLOCKER, None), (r.HELP_REQUESTED, r.WARNING, None)]


def test_no_recorder_phone_at_all_blocks():
    result = r.table_readiness([])
    assert result.status == r.BLOCKED
    assert _codes(result) == [(r.NO_RECORDER, r.BLOCKER, None)]


def test_the_only_recorder_offline_blocks_but_one_of_two_only_warns():
    alone = r.table_readiness([_recorder(connected=False)])
    assert alone.status == r.BLOCKED
    assert _codes(alone) == [(r.RECORDER_OFFLINE, r.BLOCKER, 1)]

    backed_up = r.table_readiness([_recorder(slot=1, connected=False), _recorder(slot=2)])
    assert backed_up.status == r.NEEDS_ATTENTION
    assert _codes(backed_up) == [(r.RECORDER_OFFLINE, r.WARNING, 1)]


def test_low_battery_and_low_storage_are_warnings_with_their_numbers():
    result = r.table_readiness([_recorder(battery_level=0.12, storage_free_mb=90)])
    assert result.status == r.NEEDS_ATTENTION
    assert {(x.code, x.severity) for x in result.reasons} == {
        (r.LOW_STORAGE, r.WARNING), (r.LOW_BATTERY, r.WARNING),
    }
    by_code = {x.code: x.data for x in result.reasons}
    assert by_code[r.LOW_BATTERY] == {"battery_level": 0.12}
    assert by_code[r.LOW_STORAGE] == {"storage_free_mb": 90}


def test_a_phone_that_cannot_store_or_capture_is_not_sound():
    storage = r.table_readiness([_recorder(storage_ok=False)])
    assert storage.status == r.BLOCKED
    assert _codes(storage) == [(r.LOW_STORAGE, r.BLOCKER, 1)]

    mic = r.table_readiness([_recorder(capture_ok=False)])
    assert mic.status == r.BLOCKED
    assert _codes(mic) == [(r.MIC_UNAVAILABLE, r.BLOCKER, 1)]

    # the same microphone problem on one of two recorders is a warning
    two = r.table_readiness([_recorder(slot=1, capture_ok=False), _recorder(slot=2, capture_ok=True)])
    assert two.status == r.NEEDS_ATTENTION
    assert _codes(two) == [(r.MIC_UNAVAILABLE, r.WARNING, 1)]


def test_an_upload_backlog_warns_once_it_is_two_minutes_deep():
    fine = r.table_readiness([_recorder(local_chunks=10, acked_chunks=4)])
    assert fine.status == r.READY
    stalled = r.table_readiness([_recorder(local_chunks=30, acked_chunks=10)])
    assert _codes(stalled) == [(r.UPLOAD_STALLED, r.WARNING, 1)]
    assert stalled.reasons[0].data == {"pending_chunks": 20}


def test_multiple_warnings_accumulate_and_stay_warnings():
    result = r.table_readiness([
        _recorder(slot=1, battery_level=0.1, local_chunks=40, acked_chunks=0),
        _recorder(slot=2, connected=False),
    ])
    assert result.status == r.NEEDS_ATTENTION
    expected = sorted([r.LOW_BATTERY, r.UPLOAD_STALLED, r.RECORDER_OFFLINE])
    assert sorted(x.code for x in result.reasons) == expected
    assert all(x.severity == r.WARNING for x in result.reasons)


def test_live_captions_are_a_warning_only_when_they_should_be_running():
    recording = [_recorder(live_source=False)]
    # live STT off, or the round not open: nothing to say
    assert r.table_readiness(recording, live_stt_enabled=False, round_active=True).status == r.READY
    assert r.table_readiness(recording, live_stt_enabled=True, round_active=False).status == r.READY
    # on and open, but no recording carries the captions
    none = r.table_readiness(recording, live_stt_enabled=True, round_active=True, live_source_slot=None)
    assert _codes(none) == [(r.LIVE_STT_UNAVAILABLE, r.WARNING, None)]
    # a source whose caption session failed
    failed = r.table_readiness(
        [_recorder(live_source=True)], live_stt_enabled=True, round_active=True,
        live_source_slot=1, live_caption_reason="error",
    )
    assert _codes(failed) == [(r.LIVE_STT_UNAVAILABLE, r.WARNING, 1)]
    # a healthy source: nothing
    ok = r.table_readiness(
        [_recorder(live_source=True)], live_stt_enabled=True, round_active=True, live_source_slot=1,
    )
    assert ok.status == r.READY


def test_unknown_telemetry_is_not_read_as_trouble():
    # only Chromium reports battery; a phone saying nothing is not "fine" but
    # it is not "low" either
    result = r.table_readiness([_recorder()])
    assert result.status == r.READY


def test_the_round_summary_reports_the_worst_table():
    tables = [
        {"readiness": {"status": r.READY}},
        {"readiness": {"status": r.NEEDS_ATTENTION}},
        {"readiness": {"status": r.BLOCKED}},
    ]
    assert r.summarize(tables) == {"status": r.BLOCKED, "ready": 1, "needs_attention": 1, "blocked": 1}
    assert r.summarize(tables[:2])["status"] == r.NEEDS_ATTENTION
    assert r.summarize(tables[:1])["status"] == r.READY
    assert r.summarize([])["status"] == r.READY
