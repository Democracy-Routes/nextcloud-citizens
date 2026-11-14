# Changelog

All notable changes to Citizens, from 0.7 onward. Older releases are in `CHANGELOG.md` in the repository.

## Unreleased (0.9)

### For the organizer

- Polis seeds are written in three passes (ground in the transcript excerpts,
  draft, critique with four scores) and each statement keeps its trail
  (migration 0042). A "Why" button on the row opens it: the finding, the
  claim, the excerpt with names masked and the scores; statements the critic
  scored 0 on any point are marked in the list.
- Standalone mode: Citizens runs without Nextcloud. Organizers sign in with
  an account; an administrator invites them from Settings -> Organisation ->
  Users, by mail or with a link copied from the log. The organizer page is
  served by the app itself.
- German, French and Spanish for the organizer, the recorder, the consent
  notice, the event kit and the report.
- Polis seeds: Results -> Polis seeds turns the approved findings into short,
  neutral statements (one to three per finding, under 140 characters, never
  more than 400) for a PolisOrbis conversation. Edit, approve, reject,
  reorder, add by hand, delete, or generate again; regeneration replaces only
  untouched drafts. When the analysis is re-run, statements written from a
  replaced finding keep their text and are flagged as stale. Works in both
  modes; see `docs/polis-seeds.md`.
- Polis seeds: **Approve all** approves every draft statement in one go
  (rejected ones stay rejected); `POST /api/v1/assemblies/{id}/seeds/approve-all`,
  audit event `seeds_approved_all`.
- Send to Polis: Settings -> AI -> Polis takes the instance URL and an API
  key (Citizens-Polis fork), with **Test connection**; Results -> Polis seeds
  gets **Send to Polis**, which creates the conversation (or adds the new
  statements to it) and shows the voting, moderation and report links. A
  personal-data refusal marks the statements Polis refused. Routes:
  `POST /api/v1/assemblies/{id}/seeds/push` (job `PUSH_POLIS`), settings
  `polis_url` / `polis_api_key`, test target `polis`; migration 0041; audit
  `seeds_push_requested`. See `docs/polis-seeds.md`.
- The Polis poll on the devices: once sent, **Publish the poll on the
  devices** shows the voting link and a QR code on the table phones and the
  participants' pages (recorder status `poll_url`, `GET
  /api/v1/public/recorder/poll-qr`), in the organizer's QR tab and on the
  printable table sheet; **Withdraw** takes it off. Routes `POST`/`DELETE
  /api/v1/assemblies/{id}/seeds/poll/publish`, `GET .../seeds/poll-qr`;
  audit `polis_poll_published`, `polis_poll_unpublished`.
- Seeds generation takes a number: a slider from 10 to 60 with a recommended
  value (about one per approved finding, in tens, at most 40) and an estimate
  of the voting time; findings are offered to the model by how many tables
  raised them, then proposals before concerns before questions, and the
  budget is spent breadth first (two for a disagreement). The prompt now
  demands an actor, an action and a concrete object, applies a dissent
  test and bans empty verbs, whatever the topic. `POST .../seeds/generate
  {target}`; listing fields `recommended_target`, `seeds_target`,
  `source_findings`.
- The report says what made it: every page of the PDF ends with
  "Powered by democracyroutes.com" (the Markdown too), and the methodology
  note names the analysis model(s) next to the speech-to-text engines
  ("Analysis: mistral-large-latest."), taken from the model each finding
  recorded when it was written. A report of a closed assembly shows the new
  line after **Refresh final report**; the layout needs nothing.
- One page per table in the PDF: each table of the Table detail section
  opens a fresh page with a slate banner, and the footer of its pages says
  "Table N", so a reader who opens the report in the middle knows where
  they are. Plenary reports are unchanged.
- Seeds export, available once every statement is approved or rejected:
  `<assembly>-statements.csv` (`position,statement`) or
  `<assembly>-statements.json` (schema `citizens.statement-seeds/1`). The
  files hold statement text only. Exported statements are marked EXPORTED.
- Session import: Home -> Import a session loads an `export.zip` (format
  version 1 or 2) from another server as a new, closed assembly with its
  rounds, tables, participants, recordings, transcripts and audio. Findings
  and the report are not copied; the analysis runs again here. Optional new
  name and table merges for a replacement phone. See
  `docs/recovery-and-import.md`.
- Attach audio: a table that is Audio unusable, Upload incomplete or
  Transcription failed can take a finished audio file from the Files tab;
  it is checked, stored, and transcription is queued.
- Attach transcript: a table can take a transcript file (JSON, the shape of
  `transcripts/<id>.json`) and Replace transcript behind a confirmation;
  findings that quoted the old text are flagged and the analysis is queued.

### Operations

- Resumable uploads: `POST /api/v1/uploads`, `.../parts/{n}`, `.../complete`
  (SHA-256 check) and `DELETE /api/v1/uploads/{id}`, in 5 MB parts; uploads
  belong to the organizer who opened them. Used by import and by attaching
  audio or a transcript. Routes: `POST /api/v1/assemblies/import`,
  `POST /api/v1/recordings/{id}/transcript`, `.../audio`.
- The housekeeping sweep discards unfinished uploads after 24 hours.
- Smoke (`tests/load/smoke07b.py`): the two-phone captions takeover step
  replays the sample from minute 5, where it has speech; from minute 2 it
  fed Vosk three minutes of silence and failed on 2026-11-13 for no fault
  of the server's.
- Audit events `session_imported`, `transcript_attached`, `audio_attached`.
- Fix: the analysis adapter reads a chat reply whose content is a list of
  parts (Mistral Large since 2026-11) instead of failing every table with
  `'list' object has no attribute 'strip'`; thinking parts are ignored.
- `CITIZENS_MODE=standalone` switches the mode; a value that is neither
  `standalone` nor `nextcloud` stops startup with `mode_invalid`.
- Settings are kept in an SQLite table in standalone mode.
- Invitation and reset mails over SMTP (`CITIZENS_SMTP_URL`,
  `CITIZENS_MAIL_FROM`); without SMTP the links go to the log.
- Operator commands: `python -m citizens.standalone create-admin`,
  `set-password`, `list-users`. An optional first administrator can come
  from `CITIZENS_BOOTSTRAP_ADMIN_USER` and `..._PASSWORD`.
- `CITIZENS_TRUSTED_PROXIES` tells login rate limiting which proxy's
  `X-Forwarded-For` to believe.
- `docker-compose.standalone.yml`, `.env.standalone.example`,
  `scripts/standalone-up.sh` and `scripts/standalone-down.sh`; see
  `docs/standalone.md`. `scripts/backup-citizens-data.sh` takes the volume
  name as an optional first argument.
- FastAPI and Starlette are pinned.
- Migration 0040 adds the table `statement_seeds`. New job type
  `SEED_STATEMENTS`; audit events `seeds_generation_requested`, `seed_added`,
  `seed_reviewed`, `seed_deleted`, `seeds_exported`.

## Unreleased (0.8)

### For the organizer

- Settings reorganised into four tabs — Transcription, AI, Organisation,
  About — each a column of cards with its own Save: a card's button lights up
  only when that card changed and saves only its own keys, so the single
  page-wide Save (and its "unsaved on another tab" surprise) is gone. Only
  the selected transcription service shows its card; Vosk is three cards
  (engine, models, model per language) with the legacy model label under
  Advanced. The About tab shows version, schema revision, engine state,
  disk, job queue and the last housekeeping pass, with links to the guides.
- The organizer page derives its API base from the versioned bundle URL
  (0.8's loader): fixes "Nextcloud cannot be reached … JSON parse" on Home.
- Vosk can run built into the app: Settings → Audio → Vosk offers a built-in
  engine beside a Vosk server at a URL, with a model table per language
  (small and large), one-click Install with progress and Cancel, and Remove
  (refused while a live session uses the model). Speech stays on the server.

### Operations

- The built-in engine runs on a loopback socket inside the app container;
  models live under `models/` in the data volume. A model that would not fit
  the container's free memory is refused with a clear message; two languages
  stay loaded and an idle one is unloaded after 30 minutes. Installs are
  atomic: a crash or cancel leaves nothing half-installed.
- `CITIZENS_VOSK_BUILTIN=1 scripts/event-up.sh` raises the container to 3500m
  and stops the separate Vosk container; `CITIZENS_MEMORY` overrides it.
- New admin routes: `GET /admin/vosk/models`, `POST .../{name}/install`,
  `POST .../{name}/cancel`, `DELETE .../{name}`.
- New admin route `GET /admin/about` (version, schema revision, engine
  state, disk, job counts, newest failure, last sweep) for the About tab.

## 0.7.0-beta.1 — 2026-10-16

Citizens 0.7 started on the `feature/0.7` branch; `main` immediately before
this work is tagged `pre-0.7-baseline`, and 0.6.2 stays the published release
until this one ships. The direction: a Session is the atomic unit and an
Assembly an optional container around several of them; a Table has one or
more Recorder phones with one live-caption source; a facilitator can carry a
phone of their own beside the recorders. The recorder engine, storage,
ownership, retention and export paths are extended, not rewritten.

### For the organizer

- Home opens on three actions — Record now, Start a Session, Create an
  Assembly — instead of the first assembly it finds, and a Session can grow
  into an Assembly later without losing its tables, codes or report.
- An assembly's tabs are grouped as Plan → Run → Results under a timeline of
  its sessions, and the organizer UI now speaks Italian as well as English.
- Rename an assembly or a session from the pencil on its own header; change
  an assembly's language even after recording has begun — every recording
  with audio is transcribed again, refused while a session is recording or
  once zero retention has run.
- Tables can be added mid-event, coloured for the room, and remixed between
  sessions (new people, continuity, or a plain shuffle).
- A phone report on the Files tab — browser, wake lock, chunks captured
  while hidden, gaps — also as `GET /assemblies/{id}/device-report`, the same
  analysis the host script used in rehearsals prints.
- A failed synthesis or cross-table analysis is shown on the Report tab, with
  its reason, instead of failing silently.
- Narrative synthesis across sessions, and speaking balance per table and
  across tables, on the Report and Analysis tabs.
- A pre-registration link for participants to register ahead of the table,
  "Already registered? Find your name" at the door, and a consent register
  (CSV/PDF) of every act ever recorded.
- Advanced per-recorder diagnostics on the Live tab, a link beside every QR
  code, a printed A5 event kit per table, and Settings that save only the
  fields you changed.

### At the table

- A table can run several recorder phones at once; only one feeds the live
  captions, and the captions pass to another if it stops.
- The facilitator's own phone follows the table: the question, who has
  registered, the recorders' health, the organizer's messages, a prompt to
  send, and a hand to raise — joined by its own QR code, never a recorder.
- An opt-in AI assistant nudges a table a few times a session at most — time
  running out, a silence, one voice dominating — routed to the facilitator
  first; three thumbs-down silence it there for that session.
- "No audio has reached the server" is its own readiness warning, with a
  tone the organizer can hear and a coverage percentage per recording.
- Record now has no planned time: no countdown, no auto-finish. Its done
  screen offers Record another session, and a phone's own single-use code
  still works if scanned again by the same phone; once analysed, the AI
  names the session from what was actually said.
- A recorder that sends nothing for five minutes is finished by the server
  with the audio already received; an organizer can also Finish one table's
  recording from the Live tab. Either way, audio that phone sends afterwards
  is kept, transcribed, and folded back into the table's analysis.
- A dying phone's battery prompts for a backup recorder before it dies; a
  dead phone's table can be handed to any other phone, or taken over
  automatically.
- Participants can validate their own table's summary once the report is
  published, and raise a hand for technical help, the organizer, or a
  question about the process.

### Privacy and retention

- Individual consent is recorded per person, with a refusal rule: one seated
  refusal blocks the whole table from recording until they are moved or
  change their mind.
- Consent acts are append-only — changed their mind, withdrew, moved to
  another table — the newest always counts, and nothing already recorded is
  overwritten.
- Zero retention: an assembly can be set to keep only its report. Once
  closed and fully processed, its audio, transcripts and live-caption files
  are deleted outright and a PDF of the frozen report is kept instead — this
  cannot be undone, and the assembly can never be reopened afterwards.
- One consent notice, rendered by the server from Settings and the live
  configuration, with the organization's own details and the providers
  actually selected; registration from the table's phone or the participant's
  own, with a page of their own record.
- Phone, facilitator and participant sessions that never recorded, and spent
  single-use codes, are cleaned up a week after they expire.

### Operations

- Migrations `0037` (recording close and late-audio continuation) and `0038`
  (zero retention); roll back with `alembic downgrade 0036` and the previous
  image.
- `scripts/pytest-chunks.sh` runs the whole Python suite across six
  containers at once, against a snapshot of the tree.
- A finding cites at most six quotations, and a table transcript longer than
  roughly 180,000 characters is cut for the analysis prompt, logged when it
  happens.
- A ten-table rehearsal can be run against an instance from outside, over
  the public recorder API alone, without that instance's own Docker access.

### Fixes

- Live captions survive a change of phone — a backup promoted, a takeover —
  instead of decoding nothing for the rest of the session.
- The live-caption source follows whichever recorder is actually sending
  audio, not whichever one is still on screen.
- A quiet phone no longer costs the caption connection; the recorder tells
  the organizer how many seconds it missed while hidden, and each recording
  carries its own coverage percentage.
- A table added between sessions joins only the sessions still to come; a
  participant's full name becomes one pseudonym, not one per word; a
  spontaneous table's "New table" is refused inside an organized assembly,
  where the organizer's own plan decides the tables.
- Vocabulary: a Round is a Session (Sessione N) wherever people read it,
  the software is the "AI assistant" — "facilitator" is only ever the
  person at the table — quotations are never excerpts, and reseating
  between sessions is "New seating".
