#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What each table's phone did, from its own log.

The recorder page ships a diagnostic log to the server (logs/devices/<recorder
session>.jsonl). Reading those files by hand after a rehearsal took an
afternoon and answered one question at a time. This answers the questions
that matter, per phone: which browser it was, whether it could hold the
screen awake, what happened while the page was hidden (did chunks keep
coming?), where the audio has gaps, and whether the capture watchdog
interrupted and resumed. Read-only: the database is opened read-only and the
logs are only read.

    python3 scripts/device-report.py                 # the live volume, last 24 h
    python3 scripts/device-report.py --since 6       # last six hours
    python3 scripts/device-report.py --assembly Prova
    python3 scripts/device-report.py --data /path/to/volume/_data

Standard library only, so it runs on the host as it is.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

#: consecutive local chunks further apart than this are a gap in the audio
#: (chunks are cut every 10 s; the log ships in batches, so timestamps are
#: the phone's own)
GAP_SECONDS = 15.0

#: the lines worth printing one by one
NOTABLE = (
    "wake_lock_acquired", "wake_lock_released", "wake_lock_failed", "wake_lock_unsupported",
    "capture_interrupted", "capture_resumed", "capture_resume_failed", "capture_after_background",
    "track_muted", "track_unmuted", "microphone_lost", "recorder_stop_timeout",
    "recording_started", "finish_requested", "recording_start_failed", "microphone_check_failed",
    "chunks_lost_locally", "storage_low", "js_error",
)


def resolve_data_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    for volume in ("nc_app_citizens_data", "citizens_data"):
        try:
            result = subprocess.run(
                ["docker", "volume", "inspect", volume, "--format", "{{.Mountpoint}}"],
                capture_output=True, text=True, timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    return Path("/var/lib/docker/volumes/citizens_data/_data")


def load_entries(path: Path) -> list[dict]:
    """The log's lines as dicts, in time order, exact duplicates dropped —
    the phone re-ships a batch whose acknowledgement it never saw."""
    seen: set[str] = set()
    entries: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and "event" in entry and "ts" in entry:
            entries.append(entry)
    entries.sort(key=lambda e: e["ts"])
    return entries


def browser_family(user_agent: str) -> str:
    ua = user_agent or ""
    if "iPhone" in ua or "iPad" in ua:
        if "CriOS" in ua:
            return "iOS Chrome"
        if "FxiOS" in ua:
            return "iOS Firefox"
        return "iOS Safari"
    if "Android" in ua:
        if "Firefox" in ua:
            return "Android Firefox"
        if "SamsungBrowser" in ua:
            return "Android Samsung Internet"
        if "wv" in ua or "; wv)" in ua:
            return "Android in-app browser"
        if "Chrome" in ua:
            return "Android Chrome"
        return "Android other"
    if "Firefox" in ua:
        return "desktop Firefox"
    if "Safari" in ua and "Chrome" not in ua:
        return "desktop Safari"
    if "Chrome" in ua:
        return "desktop Chrome"
    return "unknown" if not ua else "other"


def analyze(entries: list[dict]) -> dict:
    """Everything the report says about one phone, from its log lines."""
    result: dict = {
        "first_ts": entries[0]["ts"] if entries else None,
        "last_ts": entries[-1]["ts"] if entries else None,
        "user_agent": "",
        "family": "unknown",
        "standalone": None,
        "counts": Counter(e["event"] for e in entries),
        "wake_lock": Counter(),
        "hidden_windows": [],
        "gaps": [],
        "notable": [],
        "recordings": [],
        "chunks": 0,
        "upload_failures": 0,
    }
    hidden_since: float | None = None
    chunks_in_window = 0
    last_chunk_ts: float | None = None
    for entry in entries:
        event = entry["event"]
        data = entry.get("data") or {}
        if event == "device_info":
            result["user_agent"] = str(data.get("ua", ""))
            result["family"] = browser_family(result["user_agent"])
            result["standalone"] = data.get("standalone")
        elif event.startswith("wake_lock_"):
            result["wake_lock"][event] += 1
        elif event == "page_hidden":
            hidden_since = entry["ts"]
            chunks_in_window = 0
        elif event == "page_shown":
            if hidden_since is not None:
                result["hidden_windows"].append({
                    "from": hidden_since,
                    "seconds": round(entry["ts"] - hidden_since, 1),
                    "chunks": chunks_in_window,
                })
                hidden_since = None
        elif event == "chunk_saved_local":
            result["chunks"] += 1
            if hidden_since is not None:
                chunks_in_window += 1
            if last_chunk_ts is not None and entry["ts"] - last_chunk_ts > GAP_SECONDS:
                result["gaps"].append({
                    "from": last_chunk_ts,
                    "seconds": round(entry["ts"] - last_chunk_ts, 1),
                    "seq": data.get("seq"),
                })
            last_chunk_ts = entry["ts"]
        elif event == "recording_started":
            last_chunk_ts = None  # a new recording: the gap counter restarts
            result["recordings"].append({
                "ts": entry["ts"],
                "id": str(data.get("recordingId", ""))[:8],
                "mime": data.get("mimeType", ""),
            })
        elif event == "chunk_upload_failed":
            result["upload_failures"] += 1
        if event in NOTABLE:
            result["notable"].append(entry)
    if hidden_since is not None:
        result["hidden_windows"].append({
            "from": hidden_since, "seconds": None, "chunks": chunks_in_window,
        })
    return result


def _clock(ts: float | None) -> str:
    if ts is None:
        return "?"
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%H:%M:%S")


def _day(ts: float | None) -> str:
    if ts is None:
        return "?"
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")


def render(session: dict, analysis: dict) -> str:
    """One block of plain text per phone."""
    lines = [
        f"== {session.get('assembly', '?')} — table {session.get('table_number', '?')} — "
        f"session {str(session.get('id', ''))[:8]} — {_day(analysis['first_ts'])} "
        f"{_clock(analysis['first_ts'])}–{_clock(analysis['last_ts'])} UTC",
        f"   browser: {analysis['family']}"
        + ("  (installed as app)" if analysis["standalone"] else "")
        + (
            f"  [{analysis['user_agent'][:90]}]"
            if analysis["user_agent"]
            else "  (no device_info line: build before 0.6.1)"
        ),
    ]
    wake = analysis["wake_lock"]
    if wake:
        lines.append(
            "   wake lock: "
            + ", ".join(f"{name.removeprefix('wake_lock_')} ×{count}" for name, count in sorted(wake.items()))
        )
    else:
        lines.append("   wake lock: no lines (build before 0.6.2, or the page never asked)")
    recordings = analysis["recordings"]
    lines.append(
        f"   recordings: {len(recordings)}"
        + ("  " + ", ".join(f"{r['id']} at {_clock(r['ts'])}" for r in recordings) if recordings else "")
        + f"  chunks saved: {analysis['chunks']}  upload failures: {analysis['upload_failures']}"
    )
    for window in analysis["hidden_windows"]:
        verdict = (
            "still hidden"
            if window["seconds"] is None
            else f"{window['seconds']} s, {window['chunks']} chunk(s) captured while hidden"
        )
        lines.append(f"   hidden at {_clock(window['from'])}: {verdict}")
    for gap in analysis["gaps"]:
        lines.append(
            f"   GAP: {gap['seconds']} s with no local chunk after {_clock(gap['from'])}"
            + (f" (before seq {gap['seq']})" if gap.get("seq") is not None else "")
        )
    for entry in analysis["notable"]:
        if entry["event"] in ("recording_started", "wake_lock_acquired", "wake_lock_released"):
            continue  # summarised above
        data = entry.get("data") or {}
        detail = " ".join(f"{k}={v}" for k, v in data.items() if k not in ("recordingId",))
        lines.append(f"   {_clock(entry['ts'])} {entry['event']} {detail}".rstrip())
    return "\n".join(lines)


def sessions_from_db(db_path: Path, since_hours: float, assembly: str | None) -> list[dict]:
    """Recorder sessions, newest first, from the read-only database."""
    if not db_path.is_file():
        return []
    cutoff = (datetime.now(UTC) - timedelta(hours=since_hours)).strftime("%Y-%m-%d %H:%M:%S")
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        query = (
            "select rs.id, rs.table_number, rs.created_at, a.name as assembly "
            "from recorder_sessions rs join assemblies a on a.id = rs.assembly_id "
            "where rs.created_at >= ?"
        )
        params: list = [cutoff]
        if assembly:
            query += " and a.name like ?"
            params.append(f"%{assembly}%")
        query += " order by rs.created_at desc"
        return [dict(row) for row in connection.execute(query, params)]
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", help="the data volume directory (default: the live Docker volume)")
    parser.add_argument("--since", type=float, default=24.0, help="hours back to look (default 24)")
    parser.add_argument("--assembly", help="only assemblies whose name contains this")
    args = parser.parse_args(argv)

    data_dir = resolve_data_dir(args.data)
    sessions = sessions_from_db(data_dir / "citizens.db", args.since, args.assembly)
    if not sessions:
        print(f"no recorder sessions in the last {args.since:g} h under {data_dir}")
        return 1
    families: Counter = Counter()
    with_gaps = 0
    printed = 0
    for session in sessions:
        path = data_dir / "logs" / "devices" / f"{session['id']}.jsonl"
        entries = load_entries(path)
        if not entries:
            continue
        analysis = analyze(entries)
        families[analysis["family"]] += 1
        with_gaps += 1 if analysis["gaps"] else 0
        print(render(session, analysis))
        print()
        printed += 1
    print(
        f"{printed} phone(s) with a log out of {len(sessions)} session(s); "
        f"{with_gaps} with a gap over {GAP_SECONDS:g} s; browsers: "
        + (", ".join(f"{name} ×{count}" for name, count in families.most_common()) or "none")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
