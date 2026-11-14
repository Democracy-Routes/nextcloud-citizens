# Database and migrations

Citizens uses SQLite in the data volume (`citizens.db`) through SQLAlchemy 2 with a synchronous engine. Endpoints that touch the database
are plain `def` functions, so FastAPI runs them in its threadpool; the one `async def` route, chunk upload, hands its blocking work to
`run_in_threadpool`.

## SQLite settings

WAL mode and foreign keys are on, `synchronous=FULL` is used for durable upload receipts, and transactions start with `BEGIN IMMEDIATE`
so writers queue on `busy_timeout` rather than failing on a read-to-write lock upgrade. This is required for around ten devices
uploading at once. SQLite has a single writer, which is why handlers must not hold a transaction across slow external calls (see
[Jobs](jobs.md)).

## Models

Models are in `citizens/db/models/`: accounts (standalone), assembly (assemblies, rounds, tables, participants, invites, sessions),
recording (recordings, audio chunks, receipts), transcript, findings (findings and evidence), consent (notices and participant
consents), facilitator (sessions, interventions, feedback), messages, help requests, validation, seeds (`statement_seeds`), jobs
(`app_jobs`) and audit events.

## Migrations

Alembic migrations are in `citizens/db/migrations/versions/` (numbered `0001` to `0042` at the time of writing, for example
`0020` adds verification fields and the part-receipt table, `0037` and `0038` add recording close and zero-retention columns,
`0040` the seeds table, `0041` the Polis bridge columns and `0042` seed provenance).

* They run **automatically, forward only**, at every startup (`citizens/db/migrate.py`, called from `main.py`): the container upgrades its
  database to `head` before it answers requests.
* Migrations are **additive**: new columns are nullable or default-valued and new tables do not rewrite existing rows, so upgrading never
  touches existing data and a restore of an older backup upgrades itself.
* There is **no automatic downgrade**. Rolling back is a deliberate step: run Alembic directly against the volume with the old image,
  which carries the matching scripts. See [Updates and releases](../admin/updates.md#rolling-back).
* A contributor who changes the schema adds a migration; a downgrade must also exist so the rollback procedure works.

## Where files live

Binary data is in the data volume, not in the database. Everything per assembly lives under `<subdir>/<assembly_id>/`, so deleting an assembly
reaches all of it: `recordings/` (chunks), `assembled/` (audio), `transcripts/`, `live_captions/`, `exports/`, `temp/` and `logs/`. See the
[data map](../privacy/index.md).

## Audit

`services/audit.py` writes audit events for significant actions. They record event names, ids and counts, never content.
