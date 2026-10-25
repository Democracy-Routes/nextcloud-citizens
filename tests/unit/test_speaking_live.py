# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Live speaking balance from labelled caption lines (0.7 facilitator):
anonymous shares of speaking time in a rolling window, nothing when the
engine labels no speakers or too little was said."""

from citizens.services.speaking_live import engine_labels_speakers, live_balance


def _line(t, speaker, seconds=10.0, text="…"):
    return {"t": t, "end": t + seconds, "speaker": speaker, "text": text}


def test_unlabelled_captions_give_nothing_and_say_the_engine_does_not_label():
    lines = [{"t": 0, "text": "hello", "speaker": None}, {"t": 5, "text": "yes", "speaker": None}]
    assert live_balance(lines) is None
    assert engine_labels_speakers(lines) is False


def test_shares_are_of_speaking_time_in_the_window_and_sorted():
    lines = [_line(t, 0, 10) for t in range(0, 120, 12)] + [_line(t, 1, 2) for t in range(6, 120, 12)]
    lines += [_line(130, 2, 8)]
    balance = live_balance(lines)
    assert balance is not None
    assert balance["voices"] == 3
    assert balance["shares"] == sorted(balance["shares"], reverse=True)
    assert balance["largest_percent"] == balance["shares"][0] >= 70
    assert sum(balance["shares"]) in (99, 100, 101)
    assert engine_labels_speakers(lines) is True


def test_too_little_speech_is_not_a_pattern():
    assert live_balance([_line(0, 0, 10), _line(20, 1, 10)]) is None


def test_only_the_last_window_counts():
    old = [_line(t, 0, 10) for t in range(0, 600, 12)]  # voice 0 dominated ten minutes ago
    recent = [_line(t, 1, 10) for t in range(700, 1000, 12)]  # voice 1 alone in the last five
    balance = live_balance(old + recent)
    assert balance is not None
    assert balance["voices"] == 1 and balance["shares"] == [100]


def test_a_line_without_an_end_lasts_until_the_next_one_capped():
    lines = [
        {"t": 0, "speaker": 0, "text": "a"},  # until 15
        {"t": 15, "speaker": 1, "text": "b"},  # until 30
        {"t": 30, "speaker": 0, "text": "c"},  # until 50 (next is 120 s away: capped at 20 s)
        {"t": 150, "speaker": 1, "text": "d"},  # last line: 3 s
    ]
    balance = live_balance(lines)
    assert balance is not None
    assert balance["seconds"] == 15 + 15 + 20 + 3
