# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What each phone's own log says about how it behaved (R17): browser, wake
lock, chunks while hidden, gaps, watchdog events. Pure stdlib — the host
script scripts/device-report.py imports this module without the app's
dependencies, and the Files tab reads it through the API."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

GAP_SECONDS = 15.0
NOTABLE = (
    "wake_lock_acquired", "wake_lock_released", "wake_lock_failed", "wake_lock_unsupported",
    "capture_interrupted", "capture_resumed", "capture_resume_failed", "capture_after_background",
    "track_muted", "track_unmuted", "microphone_lost", "recorder_stop_timeout",
    "recording_started", "finish_requested", "recording_start_failed", "microphone_check_failed",
    "chunks_lost_locally", "storage_low", "js_error",
)




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




def analysis_payload(analysis: dict) -> dict:
    """The analysis as JSON for the Files tab: counters flattened, notable
    lines trimmed to what a reader can act on."""
    return {
        "first_ts": analysis["first_ts"],
        "last_ts": analysis["last_ts"],
        "family": analysis["family"],
        "user_agent": analysis["user_agent"][:160],
        "standalone": analysis["standalone"],
        "wake_lock": dict(analysis["wake_lock"]),
        "hidden_windows": analysis["hidden_windows"],
        "gaps": analysis["gaps"],
        "recordings": analysis["recordings"],
        "chunks": analysis["chunks"],
        "upload_failures": analysis["upload_failures"],
        "notable": [
            {"ts": e["ts"], "event": e["event"], "data": e.get("data") or {}}
            for e in analysis["notable"]
            if e["event"] not in ("recording_started", "wake_lock_acquired", "wake_lock_released")
        ][:60],
    }


def report_for_sessions(root: Path, sessions: list[dict]) -> dict:
    """{phones: [...], text: str, families: {...}} for the given recorder
    sessions ({id, table_number, slot, assembly, created_at}); a phone with
    no log lines is left out."""
    from citizens.storage.paths import device_log_path

    phones: list[dict] = []
    blocks: list[str] = []
    families: Counter = Counter()
    for session in sessions:
        entries = load_entries(device_log_path(root, session["id"]))
        if not entries:
            continue
        analysis = analyze(entries)
        families[analysis["family"]] += 1
        phones.append({
            "session_id": session["id"],
            "table_number": session.get("table_number"),
            "slot": session.get("slot", 1),
            **analysis_payload(analysis),
        })
        blocks.append(render(session, analysis))
    return {
        "phones": phones,
        "sessions": len(sessions),
        "with_gaps": sum(1 for p in phones if p["gaps"]),
        "families": dict(families),
        "text": "\n\n".join(blocks),
    }
