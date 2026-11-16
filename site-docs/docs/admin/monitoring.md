# Monitoring and logs

This page shows where to check that the app is healthy, how to read its logs and how much disk and
memory to plan for.

## Health

`GET /api/v1/health` (through the proxy in Nextcloud mode; in standalone mode an anonymous call gets only `app` and `status`) reports the database, storage, free disk and
any missing configuration. `/heartbeat` answers once the container is up and is what the image health
check uses. In Nextcloud mode:

```sh
occ app_api:app:list
docker inspect nc_app_citizens --format '{{.State.Health.Status}}'
```

## The About tab

Settings, About shows the running version, the database schema revision, the transcription engine's
state, disk space, the job queue and the time of the last housekeeping pass. It is backed by
`GET /api/v1/admin/about` (version, schema revision, engine state, disk, job counts, newest failure, last
sweep). Include it in a support request.

## During an event: `event-status.sh`

The job runner has no page of its own. `sh scripts/event-status.sh` gives the operator one screen
with the state of the system. It is read-only: it inspects the container, the host, the SQLite
database (opened read-only) and the log. It shows what is queued, retrying (and why) or failed,
memory, disk, and whether the frozen container is still the one running. Recordings that need a human
decision are listed under "needs a decision". Run it every half hour during an assembly. It finds the
AppAPI-created or hand-run volume by itself; override this with `CONTAINER` and `VOLUME_DIR`.

## Logs

The app logs with structlog: a pretty console in development and a rotating JSON-lines file,
`logs/citizens.jsonl` in the data volume (10 MB x 5). Log events carry correlation ids and contain
event names, ids and timings, never audio or transcript text; secrets are redacted on every sink.

| Install | Where to read |
|---|---|
| AppAPI-managed or hand-run | `docker logs nc_app_citizens` (or `make logs` in development) |
| Standalone | `docker compose -f docker-compose.standalone.yml logs -f citizens` |
| Any | `logs/citizens.jsonl` in the volume |

Set the detail with `CITIZENS_LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING`, `ERROR`; default `INFO`).

Useful event names: `app_started`, `public_url_resolved`, `missing_environment` (Nextcloud mode),
`missing_required_environment` and `mode_invalid` (standalone), `config_snapshot_refresh_failed`,
`job_started`, `job_failed_max_attempts`.

## Phone diagnostics

Each phone keeps an event log of its own session (browser, wake lock, chunks captured while hidden, gaps),
stored under `logs/devices/` and capped at 5 MB per session. The Files tab shows it as "Phone report";
`GET /api/v1/assemblies/{id}/device-report` returns it as JSON (or `?format=text`) and
`python3 scripts/device-report.py --since 1` prints it from the host. It contains event names and
timestamps only, plus the phone's user agent: no audio and nothing spoken.

## Audit trail

Significant actions write audit events (for example `session_imported`, `transcript_attached`,
`audio_attached`, `seeds_exported`, `seeds_push_requested`, `participant_registered`, `consent_changed`,
`participant_moved`). Retention deletions are audit-logged with assembly, policy, number of recordings and
bytes freed, never content.

## Capacity

Plan for about 10 MB per table per hour of recording plus the assembled copy. A 40-minute round of ten
tables is roughly 400 MB. A table stuck in ASSEMBLING is almost always a full disk. Unfinished upload
parts have no automatic expiry and use disk until verified assembly or explicit audio deletion.

A recording may hold 2 GiB of audio and an assembly 24 GiB; a chunk past the ceiling is refused with
413 and the phone keeps its local copy. Organizer uploads keep 1 GiB free on every part written and an
organizer may have three uploads open at a time.

On a full ten-device, half-hour run, peak container memory was 368 MiB while recording and 465 MiB
while transcribing. A 512 MB container is therefore not enough for ten tables; keep the live container
at 1 GB or more. The event scripts use 2 GiB.
