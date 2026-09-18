#!/bin/sh
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
# One screen of truth for an operator during an event. Read-only: inspects
# the container, the host, the SQLite database (opened read-only) and the log.
# The job runner has no page of its own — this is how you see it.
#
#   sh scripts/event-status.sh
set -u
CONTAINER="${CONTAINER:-nc_app_citizens}"
VOLUME_DIR="${VOLUME_DIR:-$(docker volume inspect citizens_data --format '{{.Mountpoint}}' 2>/dev/null || echo /var/lib/docker/volumes/citizens_data/_data)}"
DB="$VOLUME_DIR/citizens.db"
LOG="$VOLUME_DIR/logs/citizens.jsonl"
q() { sqlite3 -header -column "file:$DB?mode=ro" "$1" 2>&1; }

echo "== $(date -u '+%Y-%m-%d %H:%M:%S') UTC — $CONTAINER =="
docker inspect "$CONTAINER" --format \
  'state={{.State.Status}} restarts={{.RestartCount}} oom_killed={{.State.OOMKilled}} started={{.State.StartedAt}}
image={{.Config.Image}} memory_cap={{.HostConfig.Memory}} mounts={{len .Mounts}}' 2>&1
# the dev container passes --reload inside one shell string, so look at the text
cmd="$(docker inspect "$CONTAINER" --format '{{join .Config.Cmd " "}}' 2>/dev/null)"
case "$cmd" in *--reload*) echo "reload=YES  (dev container — a saved file restarts the server)";; *) echo "reload=no";; esac
docker stats --no-stream --format 'usage={{.MemUsage}} cpu={{.CPUPerc}}' "$CONTAINER" 2>&1
echo "(a mounts count above 1 or reload=YES means the DEV container is running, not the frozen one)"
echo
echo "== host =="
free -m | awk 'NR==1||NR==2{print}'
df -h "$VOLUME_DIR" | awk 'NR==2{print "volume disk: " $4 " free of " $2 " (" $5 " used)"}'
ps -eo rss,comm --sort=-rss | awk 'NR>1 && ($2 ~ /opencode|claude|codex|orca/) {n++; s+=$1} END {if (n) printf "agents still running: %d processes, %.0f MB RSS — stop them\n", n, s/1024; else print "no agent processes"}'
echo
echo "== jobs =="
q "select type, state, count(*) as n from app_jobs group by type, state order by type, state;"
echo
echo "-- live (queued / running / waiting for retry) --"
q "select type, state, attempts || '/' || max_attempts as tries, substr(next_attempt_at,12,8) as next_try_utc, substr(replace(last_error,char(10),' '),1,90) as last_error from app_jobs where state in ('QUEUED','RUNNING','RETRY') order by created_at;"
echo
echo "-- failed in the last 24h --"
q "select substr(updated_at,1,16) as at, type, substr(replace(last_error,char(10),' '),1,110) as last_error from app_jobs where state='FAILED' and updated_at > datetime('now','-1 day') order by updated_at desc limit 20;"
echo
echo "== recordings not yet ready for review, open assemblies =="
q "select a.name as assembly, r.table_number as tbl, r.state, r.error_code, r.received_chunks || '/' || coalesce(r.total_chunks,'?') as chunks, cast((julianday('now') - julianday(r.updated_at)) * 1440 as int) as min_ago from recordings r join assemblies a on a.id = r.assembly_id where a.closed_at is null and r.state not in ('READY_FOR_REVIEW','REVIEWED','UPLOAD_INCOMPLETE','AUDIO_INVALID') order by a.created_at desc, r.table_number;"
echo
echo "== rounds of open assemblies =="
q "select a.name as assembly, ro.position as round, ro.status, case when length(ro.analysis_summary) > 0 then 'yes' else 'no' end as summarised, ro.analysis_input_revision || '/' || ro.analysis_applied_revision as rev from rounds ro join assemblies a on a.id = ro.assembly_id where a.closed_at is null order by a.created_at desc, ro.position limit 12;"
echo
echo "== log: starts today, last warnings/errors =="
if [ -r "$LOG" ]; then
  today="$(date -u +%Y-%m-%d)"
  starts="$(grep "$today" "$LOG" | grep -c '"event": "app_started"')"
  printf 'app starts today: %s  (more than one means the server restarted mid-day)\n' "${starts:-0}"
  grep -E '"level": "(warning|error)"' "$LOG" | tail -20 | sed -E 's/.*"event": "([^"]+)".*"timestamp": "([^"]+)".*/\2  \1/; s/.*"timestamp": "([^"]+)".*"event": "([^"]+)".*/\1  \2/' | tail -20
else
  echo "log not readable at $LOG"
fi
