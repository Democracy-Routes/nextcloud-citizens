# Architecture

Grows alongside the code; currently covers Milestone 0.

## Overall shape

```text
                      NEXTCLOUD (32)
                           │  AppAPI (manual-install daemon, dev)
                           │  proxies /apps/app_api/proxy/citizens/* → http://nc_app_citizens:23000
                           ▼
             ┌───────────────────────────────┐
             │       NEXTCLOUD CITIZENS      │
             │  FastAPI (citizens/main.py)   │
             │  SQLite in /data (WAL, FK)    │
             │  structlog → console + jsonl  │
             └───────────────────────────────┘
```

- The ExApp is a single FastAPI process. Nextcloud authenticates every proxied
  request with the shared `APP_SECRET`; `AppAPIAuthMiddleware` (nc_py_api)
  validates it globally.
- Route access control lives in the AppAPI registration (`scripts/register.sh`
  for dev, `appinfo/info.xml` for packaged installs): `js/css/img` + `/api/v1/*`
  are USER-level, `/api/v1/admin/*` is ADMIN. Public recorder routes arrive in
  Milestone 2 with `access_level` PUBLIC. Hard-won AppAPI facts (verified
  against AppAPI 32 source and live behaviour):
  - `--json-info` registration takes **numeric** access levels (PUBLIC=0,
    USER=1, ADMIN=2); info.xml takes the string names.
  - Route URL regexes are matched against the path **without** a leading slash
    and are wrapped in `/.../i` delimiters server-side — patterns must look
    like `^js\/.*`, never `^/js/.*` (a leading `/` breaks the pattern).
  - The proxy forwards **GET, POST, PUT and DELETE only**. AppAPI registers one
    controller per verb (`ExAppProxy#ExAppGet/Post/Put/Delete`) and there is no
    PATCH handler, so a PATCH is answered **405 by Nextcloud's own router** —
    before the route table above is consulted, and without reaching the app at
    all. Partial updates therefore use PUT. `tests/unit/test_proxy_verbs.py`
    fails the build if any route or client drifts back to PATCH.
  - The proxy checks `$userId` from the **Nextcloud session** — basic auth is
    not processed on the proxy controller; browsers work, bare curl does not.
  - The browser-facing proxy URL on this server is
    `/index.php/apps/app_api/proxy/citizens/<route>` — there is no `/exapps/`
    web-server rewrite here, so client code derives its base URL from its own
    `<script src>` (see `js/citizens-main.js`).
- WebSockets do not traverse this server's nginx vhost, so all live features
  use HTTP polling / short posts by design (see
  `development-environment.md`).

## Modules (Milestone 0)

| Module | Responsibility |
|---|---|
| `citizens/main.py` | app factory, lifespan (storage → logging → DB → migrations → AppAPI handlers), request-log middleware, `enabled_handler` registering the top-menu entry + SPA script |
| `citizens/config.py` | pydantic-settings over the AppAPI environment variables |
| `citizens/logging_setup.py` | structlog: contextvar correlation IDs, secret redaction, pretty dev console + rotating `logs/citizens.jsonl` |
| `citizens/storage/paths.py` | persistent-storage layout (`recordings/`, `assembled/`, `transcripts/`, `live_captions/`, `exports/`, `temp/`, `logs/`, `citizens.db`) — everything per-assembly lives under `<subdir>/<assembly_id>/` so deleting an assembly reaches all of it |
| `citizens/db/` | SQLAlchemy 2 (sync engine — endpoints doing DB work are `def`, so FastAPI runs them in its threadpool; the one `async def` route, chunk upload, hands its blocking work to `run_in_threadpool` for the same reason), SQLite pragmas, Alembic migrations run at startup |
| `citizens/services/audit.py` | audit-event writing |
| `citizens/api/system.py` | `/api/v1/health` |
| `js/citizens-main.js` | Milestone 0 shell injected into AppAPI's embedded top-menu page (`<div id="content">`); replaced by the Vue organizer SPA in Milestone 1 |

## UI design system

The organizer SPA follows Nextcloud's native app-shell pattern: a 300 px
app-navigation sidebar (assembly list with status dots, "+ New assembly",
admin-only Settings pinned at the bottom) beside a scrollable content pane
(assembly header + icon tabs: Overview, Rounds, Participants, Tables, QR
codes, Live). On ≤768 px the sidebar becomes an overlay drawer. Shared atoms
live in `frontend/src/components/ui/` (SvgIcon via `@mdi/js`, CzButton,
CzStatusPill, CzEmptyState, CzSkeleton, CzConfirm for destructive actions,
CzToast). All styles are ID-scoped tokens over NC CSS variables (see the
"hard-won facts" above for why), adapting automatically to NC's dark theme.
The recorder keeps its own dark glanceable design (hero table number, pulsing
record ring, iconized checklist, caption bubbles).

## UI delivery model

The organizer UI is not an iframe: `enabled_handler` registers a top-menu
entry plus a script (`nc.ui.resources.set_script("top_menu", "citizens",
"js/citizens-main")`). Nextcloud's embedded template
(`/apps/app_api/embedded/citizens/citizens`) loads that script from
`/index.php/apps/app_api/proxy/citizens/js/citizens-main.js` and the script
renders into `#content`. nc_py_api auto-mounts the `js/`, `css/`, `img/`,
`l10n/` folders from the process working directory.

The recorder UI (Milestone 2) will be a separate, dependency-light bundle
served on PUBLIC routes — phones load it straight from
`/exapps/citizens/recorder/...` with no Nextcloud chrome.

## Recording pipeline (Milestones 2–3)

```text
PHONE (recorder SPA, PUBLIC routes)          SERVER
MediaRecorder (~10 s timeslices)
  └► IndexedDB FIRST (chunk + sha256)  ──►  POST chunks/{seq} (octet-stream,
       └► uploader: sequential, exp.         X-Chunk-SHA256 verified,
          backoff, online-event kick,        idempotent on rec+seq+hash)
          manual retry                          └► AudioChunk row + file
  └► oversized on 413 ──► POST parts/  (1 MiB slices, same sequence/cross-
     checked against any plain chunk of it; each part feeds live captions
     as it lands, a retried part never twice) ──► finalize assembles
finish → complete(total)              ──►  gap check → resend missing → job
       409 while ASSEMBLING = the server already has it: poll to AUDIO_READY
       and verify the manifest, never re-POST a deterministic refusal
                                            ASSEMBLE_AUDIO: concat → ffprobe
                                            → ffmpeg remux → sha256 →
                                            AUDIO_READY (state machine §24)
heartbeat every 20 s                  ──►  recorder_sessions.last_status_*
client log ring (IndexedDB)           ──►  logs/devices/<session>.jsonl
```

- Reload/crash recovery: on launch the recorder scans IndexedDB for
  unfinished recordings and resumes synchronization (mic session itself
  cannot survive a reload; every persisted chunk does).
- SQLite concurrency: transactions run `BEGIN IMMEDIATE` (writers queue on
  `busy_timeout` instead of failing on read→write lock upgrades) — required
  for ~10 devices uploading simultaneously (§56 Test F).
- Facilitator "Live" tab polls `/rounds/{id}/monitor`: device connectivity
  (heartbeat age), chunk upload progress, and "local recording safe" only
  when a recent heartbeat reports healthy storage.
- Round start/end is organizer-controlled; recorders only ever poll — the
  server never reaches into a phone. In orchestrated mode the phone *arms*
  itself on an explicit READY tap (that tap is the user gesture + consent and
  opens the mic), then polling turns facilitator start/end into auto
  start/finish. In independent mode the tap starts recording directly.

## Recording modes (per assembly)

- **Orchestrated** (live event, the default): tables tap READY once and sit
  on an Armed screen sending `armed` heartbeats. The Live tab shows
  "N/M tables ready" and warns (never blocks) when starting incomplete.
  Facilitator Start → armed phones begin recording together; the server
  rejects `recorder/start` for rounds that are not ACTIVE (409). Facilitator
  End → phones show a 15 s cancellable "finishing" countdown ("Keep talking"
  aborts), then finish and synchronize; the done screen re-arms for the next
  round automatically.
- **Independent** (async): rounds act as shared questions, not timed windows.
  Each table records any un-recorded round on its own schedule (days apart if
  needed); Start/End round controls are hidden on the Live tab. Cross-table
  clustering re-runs incrementally as each table's analysis lands (draft
  round findings are replaced, reviewed ones kept).
- **Plenary** (one shared recorder): the whole room is a single discussion
  captured by many phones at once — 30 people in a circle, or one person
  recording a meeting. Facilitator-led like orchestrated (arm, the facilitator
  opens/ends the one shared round), but the "one recording per table" guard is
  lifted: a plenary assembly is one table joined by one shared code, and any
  number of devices record the same round concurrently. The phone-side "already
  recorded" state is scoped per device so no phone locks another out.
- Orchestrated and independent: one healthy recording per table+round; the
  recorder locks after finish so no stray recordings appear. Plenary is the
  exception — concurrent recordings on the one table are the point.

### Merging the room's devices

Several phones capture the same talk from different spots, so their transcripts
overlap; concatenating them would count each statement once per phone. Instead
`merge_plenary_segments` (`citizens/services/analysis.py`) aligns every
segment on the server clock — `recording.started_at + segment.start_seconds`,
which is the shared time reference across devices — coalesces within each device
first, then drops near-duplicate utterances from *different* devices within a
few-second window (a stdlib `difflib` fuzzy match), keeping the longer/cleaner
copy and its segment ids so evidence citations stay valid. A line only one phone
caught survives. The merged transcript feeds one `analyze_table`, so findings,
evidence and the report are unchanged. `started_at` is the `/start` moment, not
the first audio sample, so a per-device offset of a second or two is expected
and the window absorbs it; audio cross-correlation is deliberately out of scope.
Speakers are not unified across devices (diarization is per-recording).

Every device transcribes independently, so plenary costs N× transcription for
one discussion — the trade for multi-position coverage. The "wait for all the
table's recordings to finish transcribing before analysing" barrier
(`_table_still_transcribing`) already holds the group together, unchanged.

## Losing a phone mid-round

The server cannot distinguish a dead battery from dead WiFi: both simply stop
sending chunks. That single fact shapes the whole design, because the right
response differs — a dead phone has stopped recording, while a disconnected one
is still recording locally and will upload the backlog when it returns.

So there are two release paths, and they deliberately behave differently:

- **`POST /recordings/{id}/replace-device`** (the facilitator's *Replace
  device*): a person looked at the phone and it is finished. The recording is
  moved to `UPLOAD_INCOMPLETE` with `error_code=DEVICE_REPLACED`, stamped
  `superseded_at`, and — if any chunk arrived — assembled and transcribed, so
  the half already recorded is not thrown away.
- **The automatic takeover** in `start_recording`: no chunk for
  `STALLED_DEVICE_SECONDS` (120) while still `RECORDING`. A timer only guesses,
  so the original recording is left **open**, and a phone that was merely
  offline can still upload everything it captured while disconnected.

`superseded_at` exists because the salvage path defeated itself otherwise:
assembling the partial audio moves the recording into `ASSEMBLING`, which is
not a re-recordable state, so the replacement phone was still refused. The
column marks "this belonged to a device that has gone" independently of state,
and every guard that asks "has this table recorded this round?" ignores rows
carrying it.

Two things the phone is told, both scoped to the *session* rather than the
table, because the table-level view cannot tell one phone from another:

- a recording whose device has gone silent is omitted from the phone's view of
  what has been recorded — without this the takeover was reachable by the API
  and unreachable by an actual phone, which only asks to start a round it
  believes is open;
- each round reports whether *this* session made the recording holding it, so a
  phone is never told its own work belongs to somebody else.

Both halves of the round are analysed as one table (`table_recordings()`), with
a methodology note that the device changed, so the report reads as one
discussion rather than two fragments.

## Ending a round

Nothing server-side acts on `duration_minutes`; there is no timer or sweep for
it. Independent tables finish themselves from the phone's own clock, and
orchestrated rounds used to run until a facilitator clicked — which is why
tables drifted apart, since each one's recording starts when its phone sees the
round open.

The Live tab now drives the ending: past the planned time it counts up, and
after a minute's grace calls the same `end_round` a click would. Deliberately
client-side rather than a sweep — the facilitator has that tab open, it is
where rounds are started, and a server that ended rounds while nobody was
watching would end one during a break. The cost is stated plainly in the admin
guide: with the tab closed, nothing ends by itself.

An extension is held in the tab rather than written to the round. The stored
duration is what the assembly was *planned* for, and rewriting it would quietly
edit the record of what was run; a reload forgets the extension and asks again,
which is the safe direction to fail.

## Clearing audio off the phones

Recording offline-first means every phone keeps its table's audio after the
event — which matters when participants used their own devices. Closing the
assembly sets `device_audio_purge_requested_at` — automatically when
`auto_purge_device_audio` is on, which is the default, or on demand from **Clear
audio from the table phones**. The server cannot push, so the flag rides the
status poll every recorder already makes.

**Reopening withdraws the automatic request.** The phone-facing value is a
bare "has this been asked for" and is never re-checked against `closed_at`,
so a request left standing through a reopen would tell every phone in the
reopened assembly to delete — clearing each *new* recording the moment it
reached `AUDIO_READY`, mid-round. `purge_requested_automatically`
(migration 0021) records *who* asked: reopening withdraws the request only
when the close made it, and it does so independently of the
`auto_purge_device_audio` toggle's current value — flipping the toggle off
between close and reopen must not leave a delete request standing over an
assembly whose organizer just said to keep the local copies. A request the
organizer sent by hand from the Files tab stands until the phones have
answered it. Requests that predate the column are backfilled as automatic:
the migration cannot know who asked, and a request that stands too long
deletes audio, while one withdrawn too early is at worst re-sent.

The guarantee is one-directional and deliberate: a phone deletes only audio the
server has already confirmed. Anything unconfirmed is kept and the phone says
so, because the alternative — a request that could destroy the last copy of a
discussion — is not worth the tidiness. The Files tab reports coverage
("6 of 8 table phones have reported clearing their copy"), never completion: a
phone closed and carried out of the building never receives the request at all,
and one that has not reported since will clear itself if it is opened again.

## Analysis output

- Every analyzed table stores a mandatory neutral AI `analysis_summary`
  (2–4 sentences, assembly language) alongside findings; rounds store a
  cross-table summary. Summaries always render in the Analysis tab and
  reports labeled as AI-generated, so a session with no substantive findings
  (small talk) still reads as "analyzed", not as an empty failure state.
  Findings remain evidence-linked drafts until human review.
- STT models are configured separately for live captions and final
  transcription per provider (Deepgram live/batch, Mistral batch; Mistral
  live reserved for Voxtral Realtime).
- Live captions and final transcription are independent switches. With final
  off, a finished caption session's lines are written to `live_captions/` and
  the `TRANSCRIBE_FROM_LIVE` job turns them into a real `Transcript` through the
  same `store_transcript()` the provider adapters use — so analysis, evidence
  citations and reports need no special case. `transcripts.source`
  (`final`/`live`, migration 0014) records which happened, and drives a line in
  the report's methodology note.
- A caption session keeps every line it produced, not the window it displays:
  `status()` returns the last `MAX_LINES` for the phone while `session.lines`
  holds the whole round. Persisting appends to any file already there, so a
  session that dies and reconnects does not erase what preceded it.

## Dev workflow

```text
edit code → uvicorn auto-reloads (source bind-mounted) → refresh browser
```

- `make up` — build image, start `nc_app_citizens` (512 MB memory cap) on the
  Nextcloud docker network.
- `make register` — register manual-install daemon + ExApp (idempotent).
- `make logs`, `make test`, `make lint`, `make dev-reset` (Citizens data only).
- The AppAPI shared secret is generated once into `.app_secret` (gitignored).

## Vocabulary: Session and Round (0.7)

Citizens 1.0 talks about an optional **Assembly** (an organized event), the
**Session** (one question discussed at one or more tables — the unit a user
starts from, on its own or inside an Assembly), the **Table** (one discussion
within a Session, numbered and coloured) and the **Recorder** (a phone
recording a Table; one or more per Table).

The schema and the recording pipeline still spell a Session as `Round`:
`rounds`, `round_id`, the `/rounds/{id}` routes, the `Round` model, and ~1,600
references through recording, transcription, analysis, reports and tests. A
standalone Session is a `Round` inside a container `Assembly(kind="session")`
that the UI never presents as an assembly (`services/sessions.py`). None of
that is renamed in 0.7 — `round_id` is wired through the one part of the app
that must never wobble — so the bridge is:

- new product and API surfaces say Session (`POST /sessions`,
  `GET /sessions`, `GET /sessions/{id}`, `session_id` in their payloads, the
  organizer's labels, the phone's strings);
- existing routes, columns and internals keep Round, and a `session_id` in a
  Session payload *is* a round id — every `/rounds/{id}` route accepts it;
- reports still print "Round N" headings (`report.round_heading`); the
  report vocabulary moves in a later step with its own fixtures;
- `recorder_sessions` is a phone's bearer session — a different thing. No
  recorder code uses a bare `session_id` to mean a Session.

`citizens/domain/vocabulary.py` states the mapping once.

## Standalone Sessions (0.7)

"Record now" and "Start a Session" create a Session with no assembly to name
or configure: `services/sessions.py` builds a container `Assembly(kind=
"session")` named after the question, one round, its tables and QR codes, and
for Record now returns Table 1's join link in independent mode so the phone
that opens it records at once. The container exists because every storage
path, ownership check, retention sweep, device-audio purge, export and report
is keyed by `assembly_id`; the organizer UI lists it under "Sessions", never as
an assembly, and nothing new asks the caller for one. Rounds carry an optional
`objective` ("produce three concrete proposals") beside the `question`; it
reaches the phone, the analysis prompts and the reports, and is NULL on every
pre-0.7 round.

## Tables: number, colour, growth (0.7)

A `Table` row is per round; the table the room knows is the **number**, the
same in every round, printed on the QR sheet and carried by every phone and
recording. Beside it a **colour** (`tables.color_key`, from a six-colour
palette by number, repeating after six) is a cue for a room looking for "the
blue table" and never something correctness depends on. `services/tables.
add_table()` adds the next number to every round at once and issues its code
without touching the codes on the wall; numbers are allocated max+1 under
SQLite's writer lock with the (round, number) unique constraint as backstop.
`default_table_count` only seeds rounds added later — completeness and the
report count the rows that exist.

## Capabilities: the first phone decides (0.7)

A phone that already joined makes the QR code for the next phone, and the code
carries its meaning: `ADD_RECORDER_TO_TABLE` (the scanner joins this table as
another recorder) or `ADD_TABLE` (the next table is created and the scanner is
its first recorder). The scanner never chooses. Both share the row, hashing,
vault, rate limit, brute-force protection and `#/join` route with the printed
table codes (`recorder_invites.purpose`; `services/capabilities.py`); they
live fifteen minutes and are single-use — the first scan claims `consumed_at`
with a conditional UPDATE under the writer lock, the second gets 410 — while
printed table codes stay reusable so a replacement phone still rescans the
poster. Creation and consumption are audited by invite id, never by token. A
future stable physical-table code is simply a reusable `JOIN_TABLE` row with
no round, which nothing here forecloses.

## Several recorders per table, one live source (0.7)

`recorder_sessions.slot` numbers a table's recorders: the table's own code is
slot 1 (a replacement that rescans it too — same role), an added recorder gets
the next number, and slots are never reused. The one-recording-per-table guard
holds **per slot**, so recorders in different slots record side by side while
every recovery path (own-recording reclaim, "record the rest", silent-device
takeover, the 409) is unchanged within a slot. `services/table_recordings.py`
is the home of "every recording of this table"; the analysis merges recordings
that overlap in time (as plenary always did) and concatenates ones that follow
each other, deciding by time rather than by how the recording came to exist.

Only one recording per table feeds the live captions: `recordings.live_source`
with a partial unique index (`services/live_source.py`). The first recorder to
start takes it, a backup's chunks are stored but never handed to the caption
engine (its `/live` poll says whose captions it is watching), any recorder
still in progress can be promoted from its phone or by the organizer, and
every path that stops a recording passes the source to a sibling still
recording. Plenary rooms therefore open one streaming session, not N.

## Table readiness (0.7)

`services/readiness.py` turns what the monitor already knows — heartbeat age,
the heartbeat payload, each recorder's recording, the live source — into
READY / NEEDS_ATTENTION / BLOCKED with structured reason codes
(`NO_RECORDER`, `RECORDER_OFFLINE`, `MIC_UNAVAILABLE`, `LOW_STORAGE`,
`LOW_BATTERY`, `UPLOAD_STALLED`, `LIVE_STT_UNAVAILABLE`), each a blocker or a
warning naming the recorder concerned. Not every problem blocks: one healthy
recorder with no backup is READY; the only recorder offline is BLOCKED. It is
on every table in the monitor payload and at `GET /rounds/{id}/readiness`, and
is what an exception-first screen and an organizer's autopilot build on.
