# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""scripts/device-report.py: a phone's log, read for the questions that
matter after a rehearsal — did it record with the screen off, where are the
gaps, could it hold the screen."""

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("device_report", ROOT / "scripts" / "device-report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _line(ts, event, data=None, level="info"):
    entry = {"ts": ts, "level": level, "event": event}
    if data:
        entry["data"] = data
    return json.dumps(entry)


def _write(tmp_path, lines):
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_hidden_windows_gaps_and_notable_lines(tmp_path):
    report = _module()
    t = 1_700_000_000.0
    path = _write(tmp_path, [
        _line(t, "device_info", {
            "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7) Safari/605.1", "standalone": False,
        }),
        _line(t + 1, "wake_lock_acquired"),
        _line(t + 2, "recording_started", {"recordingId": "abcdef12-0000", "mimeType": "audio/mp4"}),
        _line(t + 12, "chunk_saved_local", {"seq": 0, "bytes": 100}),
        _line(t + 22, "chunk_saved_local", {"seq": 1, "bytes": 100}),
        _line(t + 25, "page_hidden", level="warn"),
        _line(t + 25.1, "wake_lock_released", {"visible": False}, level="warn"),
        _line(t + 85, "page_shown", level="warn"),
        _line(t + 85.2, "capture_after_background", {"hiddenMs": 60000, "chunksWhileHidden": 0}),
        _line(t + 117, "capture_interrupted", {"cause": "capture_stalled", "segment": 0}, level="error"),
        _line(t + 118, "capture_resumed", {"segment": 1, "interruptedMs": 1000}, level="warn"),
        _line(t + 128, "chunk_saved_local", {"seq": 2, "bytes": 100, "segment": 1}),
        # the same batch shipped twice: dropped, not counted twice
        _line(t + 128, "chunk_saved_local", {"seq": 2, "bytes": 100, "segment": 1}),
    ])

    analysis = report.analyze(report.load_entries(path))

    assert analysis["family"] == "iOS Safari"
    assert analysis["wake_lock"] == {"wake_lock_acquired": 1, "wake_lock_released": 1}
    assert analysis["hidden_windows"] == [{"from": t + 25, "seconds": 60.0, "chunks": 0}]
    assert analysis["chunks"] == 3
    assert len(analysis["gaps"]) == 1
    assert analysis["gaps"][0]["seconds"] == 106.0
    assert [r["id"] for r in analysis["recordings"]] == ["abcdef12"]

    text = report.render({"assembly": "Prova", "table_number": 3, "id": "11112222-3333"}, analysis)
    assert "Prova — table 3" in text
    assert "iOS Safari" in text
    assert "0 chunk(s) captured while hidden" in text
    assert "GAP: 106.0 s" in text
    assert "capture_interrupted cause=capture_stalled" in text
    assert "capture_resumed segment=1" in text


def test_an_android_that_records_in_the_background_shows_no_gap(tmp_path):
    report = _module()
    t = 1_700_000_000.0
    lines = [
        _line(t, "device_info", {"ua": "Mozilla/5.0 (Linux; Android 15) Firefox/155.0"}),
        _line(t + 1, "recording_started", {"recordingId": "r", "mimeType": "audio/webm"}),
        _line(t + 5, "page_hidden", level="warn"),
    ]
    lines += [_line(t + 10 * n, "chunk_saved_local", {"seq": n - 1}) for n in range(1, 30)]
    lines.append(_line(t + 300, "page_shown", level="warn"))
    path = _write(tmp_path, lines)

    analysis = report.analyze(report.load_entries(path))

    assert analysis["family"] == "Android Firefox"
    assert analysis["gaps"] == []
    assert analysis["hidden_windows"][0]["chunks"] == 29


def test_a_log_with_no_device_info_is_still_readable(tmp_path):
    report = _module()
    path = _write(tmp_path, [
        "not json at all",
        _line(1.0, "recording_started", {"recordingId": "x"}),
        _line(2.0, "chunk_saved_local", {"seq": 0}),
    ])

    analysis = report.analyze(report.load_entries(path))

    assert analysis["family"] == "unknown"
    assert analysis["chunks"] == 1
    assert "build before 0.6.1" in report.render({}, analysis)


def test_browser_families():
    report = _module()
    android = "Mozilla/5.0 (Linux; Android 14"
    assert report.browser_family(f"{android}; wv) Chrome/120") == "Android in-app browser"
    assert report.browser_family(f"{android}) Chrome/120 Mobile Safari") == "Android Chrome"
    assert report.browser_family("Mozilla/5.0 (iPhone) CriOS/120") == "iOS Chrome"
    assert report.browser_family("") == "unknown"
