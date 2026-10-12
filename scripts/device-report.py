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
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

#: consecutive local chunks further apart than this are a gap in the audio
#: (chunks are cut every 10 s; the log ships in batches, so timestamps are
#: the phone's own)
# the analysis itself lives with the app, so the Files tab shows the same
# report (citizens/services/device_report.py is stdlib-only on purpose)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from citizens.services.device_report import (  # noqa: E402
    GAP_SECONDS,
    analyze,
    load_entries,
    render,
)


#: the lines worth printing one by one
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
