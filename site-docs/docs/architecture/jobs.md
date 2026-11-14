# Jobs and background work

Long-running work (assembling audio, transcription, analysis, seeds, mail, model installs) runs as durable jobs. The runner is in
`citizens/jobs/runner.py`, the handlers in `citizens/jobs/handlers.py` and the periodic upkeep in `citizens/jobs/sweep.py`.

## The durable queue

Jobs live in SQLite (the `app_jobs` model `AppJob`) with a type, a JSON payload, a state, attempts and `next_attempt_at`. States that
mean "this work will still happen" are `QUEUED`, `RUNNING` and `RETRY`. Enqueueing is `enqueue_job()` in `services/jobs.py`;
`has_live_job()` lets callers avoid acting on something a job is in the middle of, such as abandoning a recording that is being assembled.

| Job type | Does |
|---|---|
| `ASSEMBLE_AUDIO` | concatenates chunks, probes with ffprobe, remuxes with ffmpeg, checksums, moves the recording to AUDIO_READY |
| `TRANSCRIBE_FINAL` | transcribes the assembled audio with the configured provider |
| `TRANSCRIBE_FROM_LIVE` | turns a finished caption session into a transcript |
| `ANALYZE_TABLE` | per-table findings and summary |
| `ANALYZE_ROUND` | cross-table clustering for a round |
| `ANALYZE_ASSEMBLY` | narrative synthesis across sessions |
| `SEED_STATEMENTS` | Polis statements from approved findings |
| `PUSH_POLIS` | sends approved statements to the configured Polis instance |
| `INSTALL_VOSK_MODEL` | downloads and installs a built-in Vosk model |
| `SEND_MAIL` | invitation and reset mails in standalone mode |

## Workers, retries and leases

* The runner polls every 3 seconds for due work and executes handlers in worker threads, up to `CITIZENS_JOB_WORKERS` at once
  (default 10; `1` runs one after another).
* On failure a job backs off exponentially: 30 seconds doubled per attempt, capped at one hour. After `max_attempts` (5 by default)
  it is `FAILED`. A provider-supplied retry delay is honoured within that cap.
* A job waiting only for a transcription slot (`CapacityBusyError`) is retried every 60 seconds and the attempt is given back.
  `PermanentJobError` fails without retrying.
* On startup, stale `RUNNING` jobs from a crash or restart are recovered to `RETRY`. A `RUNNING` job that holds its lease for more than
  1800 seconds is reclaimed.
* Claiming marks a job `RUNNING` inside its own write transaction, so two workers can never take the same job. Exactly one
  runner loop (one container) is supported against a database.

!!! warning "The contract for handlers"
    Handlers run inside one session whose transaction takes SQLite's single write lock. A handler must `commit()` right before any long
    external call (ffmpeg, a speech-to-text or model request). A transaction held across those starves every API request into 500
    errors after `busy_timeout`. Guard tests in the suite fail the build on this class of mistake; see [Testing](testing.md).

## Sweeps

`run_sweeps()` runs every 60 seconds (`SWEEP_INTERVAL_SECONDS`). Sweeps are best effort: a failure is logged and retried on the next
tick, and must never take a recording's audio with it. They exist because the reactive queue only acts when something enqueues work,
and a phone whose battery dies mid-upload enqueues nothing. The sweeps include:

* missed enqueues and superseded partial recordings;
* server closes: a recorder silent for 300 seconds, or a Finish requested from the Live tab and unanswered for 90 seconds;
* stalled uploads (the 20-minute timeout and the automatic assembly 30 minutes after that);
* expired audio under the retention policy, and stale export archives (an hour);
* expired sessions and spent single-use codes (removed seven days after they expired);
* zero retention, built-in Vosk reconciliation, the AI facilitator's minute tick, unfinished uploads (24 hours), and the config
  snapshot refresh.

## Configuration is read in the background

Provider configuration in Nextcloud mode is an OCS call to Nextcloud. Reading it from a request holds a database connection across a
network call; in 2026-09 five phones recording drove 85 such calls a minute, slowed Apache, and exhausted the connection pool. No
request path reads Nextcloud any more: a single `ConfigSnapshot` is refreshed in the background (at startup, on every sweep, right
after Settings are saved, and in a helper thread when a reader finds it older than 30 seconds), and readers only look at memory. A
failed refresh keeps the previous values. Do not add a request path that reads configuration directly.
