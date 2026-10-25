# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The device report (R17): what a phone's own log says, as the script and
the Files tab both read it."""

import json

from citizens.services import device_report
from citizens.services.analysis import _cap_transcript_lines, _first_evidence
from citizens.storage.paths import device_log_path


def _log(root, session_id, entries):
    path = device_log_path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


def _entries():
    t = 1_760_000_000.0
    return [
        {"ts": t, "event": "device_info",
         "data": {"ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari", "standalone": True}},
        {"ts": t + 1, "event": "wake_lock_acquired"},
        {"ts": t + 2, "event": "recording_started",
         "data": {"recordingId": "abcdef1234", "mimeType": "audio/mp4"}},
        {"ts": t + 12, "event": "chunk_saved_local", "data": {"seq": 0}},
        {"ts": t + 22, "event": "chunk_saved_local", "data": {"seq": 1}},
        {"ts": t + 23, "event": "page_hidden"},
        {"ts": t + 83, "event": "page_shown"},
        {"ts": t + 84, "event": "chunk_saved_local", "data": {"seq": 2}},
        {"ts": t + 85, "event": "capture_interrupted", "data": {"reason": "stall"}},
        {"ts": t + 85, "event": "capture_interrupted", "data": {"reason": "stall"}},  # re-shipped
    ]


def test_analysis_reads_browser_hidden_windows_and_gaps(settings_env):
    root = settings_env.app_persistent_storage
    _log(root, "sess-1", _entries())
    entries = device_report.load_entries(device_log_path(root, "sess-1"))
    assert len(entries) == 9, "an exact duplicate line is dropped"
    analysis = device_report.analyze(entries)
    assert analysis["family"] == "iOS Safari" and analysis["standalone"] is True
    assert analysis["chunks"] == 3 and analysis["wake_lock"]["wake_lock_acquired"] == 1
    assert analysis["hidden_windows"] == [{"from": 1_760_000_023.0, "seconds": 60.0, "chunks": 0}]
    assert len(analysis["gaps"]) == 1 and analysis["gaps"][0]["seconds"] == 62.0
    text = device_report.render({"assembly": "A", "table_number": 1, "id": "sess-1"}, analysis)
    assert "iOS Safari" in text and "GAP: 62.0 s" in text and "capture_interrupted reason=stall" in text


def test_report_for_sessions_skips_phones_without_a_log(settings_env):
    root = settings_env.app_persistent_storage
    _log(root, "sess-1", _entries())
    report = device_report.report_for_sessions(root, [
        {"id": "sess-1", "table_number": 1, "slot": 1, "assembly": "A"},
        {"id": "sess-2", "table_number": 2, "slot": 1, "assembly": "A"},
    ])
    assert report["sessions"] == 2 and len(report["phones"]) == 1 and report["with_gaps"] == 1
    assert report["families"] == {"iOS Safari": 1}
    phone = report["phones"][0]
    assert phone["session_id"] == "sess-1" and phone["notable"][0]["event"] == "capture_interrupted"
    assert "table 1" in report["text"]


def test_browser_families():
    family = device_report.browser_family
    assert family("Mozilla/5.0 (Linux; Android 14; wv) Chrome/120") == "Android in-app browser"
    assert family("Mozilla/5.0 (Linux; Android 14) Chrome/120 Mobile") == "Android Chrome"
    assert device_report.browser_family("Mozilla/5.0 (iPhone) CriOS/120") == "iOS Chrome"
    assert device_report.browser_family("") == "unknown"


class _Segment:
    def __init__(self, id):
        self.id = id


def test_evidence_is_capped_in_spoken_order_and_the_prompt_is_bounded():
    segments = [_Segment(f"s{i}") for i in range(20)]
    kept = _first_evidence({f"s{i}" for i in (19, 3, 7, 1, 12, 5, 9, 0)}, segments)
    assert kept == {"s0", "s1", "s3", "s5", "s7", "s9"}
    lines = ["x" * 1000 for _ in range(300)]
    capped = _cap_transcript_lines(lines, "rec")
    assert len(capped) < 300 and capped[-1].startswith("[transcript truncated here:")
    assert sum(len(line) + 1 for line in capped[:-1]) <= 180_000
    assert _cap_transcript_lines(lines[:10], "rec") == lines[:10]
