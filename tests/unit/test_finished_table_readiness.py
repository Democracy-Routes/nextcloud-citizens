# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A finished table is not a problem (0.8): once the round is over and no
recording is open, the phones' old heartbeats mean nothing."""

from citizens.services import readiness


def _stale(slot, state="READY_FOR_REVIEW"):
    return {
        "slot": slot, "connected": False, "seconds_since_contact": 100,
        "status": {"capture_ok": None, "pending_chunks": 1},
        "recording": {"state": state, "live_source": False, "silent_seconds": None},
    }


def test_a_finished_table_is_ready_with_no_reasons():
    result = readiness.table_readiness([_stale(1), _stale(2)], nothing_left=True)
    assert result.status == readiness.READY and result.reasons == []


def test_a_finished_table_keeps_its_hand_up():
    result = readiness.table_readiness([_stale(1)], nothing_left=True, help_requested="PROCESS")
    assert result.status == readiness.READY
    assert [r.code for r in result.reasons] == [readiness.HELP_REQUESTED]


def test_the_same_phones_are_a_problem_while_something_is_left():
    result = readiness.table_readiness([_stale(1), _stale(2)], nothing_left=False)
    assert result.status != readiness.READY
    assert readiness.RECORDER_OFFLINE in [r.code for r in result.reasons]
