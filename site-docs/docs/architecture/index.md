# Architecture overview

Citizens is a single FastAPI process (`citizens/main.py`) with SQLite in the data volume, a Vue
organizer and a dependency-light phone recorder. It runs in two modes: as a Nextcloud ExApp behind the
AppAPI proxy, or standalone with its own sign-in. This page maps the modules; the pages linked at the
end go deeper.

## Overall shape

```text
                      NEXTCLOUD (32)
                           |  AppAPI
                           |  proxies /apps/app_api/proxy/citizens/* -> http://nc_app_citizens:23000
                           v
             +-------------------------------+
             |           CITIZENS            |
             |  FastAPI (citizens/main.py)   |
             |  SQLite in /data (WAL, FK)    |
             |  structlog -> console + jsonl |
             +-------------------------------+
```

In Nextcloud mode every proxied request is authenticated with the shared `APP_SECRET`, and
`AppAPIAuthMiddleware` (nc_py_api) validates it globally.

Route access control lives in the AppAPI registration: `scripts/register.sh` for development and
`appinfo/info.xml` for packaged installs. `js`, `css`, `img` and `/api/v1/*` are USER level,
`/api/v1/admin/*` is ADMIN, and the recorder routes are PUBLIC.

In standalone mode (`CITIZENS_MODE=standalone`) the app serves its own organizer page, signs organizers
in with cookies and stores Settings in an SQLite table. No Nextcloud code path is involved.

### AppAPI facts that shape the code

These were checked against the AppAPI 32 source and live behavior.

* `--json-info` registration takes numeric access levels (PUBLIC=0, USER=1, ADMIN=2); `info.xml`
  takes the string names.
* Route URL regexes are matched against the path without a leading slash on AppAPI 33 and earlier, and
  with one on 34 and later. They are wrapped in `/.../i` delimiters server side. The escaped form
  `^api\/v1\/.*` works on both.
* The proxy forwards GET, POST, PUT and DELETE only. Nextcloud's own router answers a PATCH with 405
  before the app is reached, so partial updates use PUT. `tests/unit/test_proxy_verbs.py` fails the
  build if any route or client drifts back to PATCH.
* The proxy checks the Nextcloud session: browsers work, bare `curl` does not.
* The browser-facing proxy URL is `/index.php/apps/app_api/proxy/citizens/<route>`. Client code derives
  its base URL from its own `<script src>`.
* WebSockets do not traverse the proxy path, so all live features use HTTP polling and short posts.

## Modules

| Module | Responsibility |
|---|---|
| `citizens/main.py` | app factory, lifespan (storage, logging, database, migrations, AppAPI handlers), request-log middleware, `enabled_handler` registering the top-menu entry and SPA script |
| `citizens/config.py` | pydantic-settings over the AppAPI environment variables (and the standalone ones) |
| `citizens/logging_setup.py` | structlog: contextvar correlation ids, secret redaction, console and rotating `logs/citizens.jsonl` |
| `citizens/storage/paths.py` | persistent-storage layout (`recordings/`, `assembled/`, `transcripts/`, `live_captions/`, `exports/`, `temp/`, `logs/`, `citizens.db`); everything per-assembly lives under `<subdir>/<assembly_id>/`, so deleting an assembly reaches all of it |
| `citizens/db/` | SQLAlchemy 2 with a sync engine (endpoints doing database work are `def`, so FastAPI runs them in its threadpool), SQLite pragmas, Alembic migrations run at startup |
| `citizens/api/` | route modules: assemblies, sessions, findings, files, reports, seeds, imports, admin, recorders and facilitator public routes, auth and users |
| `citizens/services/` | domain logic: recording, transcription, analysis, report, consent, seeds, Polis, retention, zero retention, Vosk |
| `citizens/providers/` | transcription adapters (Deepgram, Mistral, Whisper, Vosk) and the OpenAI-compatible analysis adapter |
| `citizens/jobs/` | the durable job runner, handlers and periodic sweeps ([Jobs](jobs.md)) |

## UI delivery

The organizer UI is not an iframe. In Nextcloud mode `enabled_handler` registers a top-menu entry and
a script. Nextcloud's embedded template loads `js/citizens-main.js` through the proxy, and the script
renders into `#content`.

The recorder is a separate bundle (`recorder_static/`) served on PUBLIC routes. Phones load it straight
from the proxy with no Nextcloud chrome. The proxy sends `default-src 'none'` as CSP for proxied
responses, so the recorder page ships its own CSP header, and its path must end in `.html` for the
proxy to inject a script nonce. The proxy caches assets for an hour; the recorder busts this with the
app version in its URLs. See [Frontend](frontend.md).

## Vocabulary

The product says Assembly, Session, Table and Recorder; the schema and routes still spell a Session as
a `Round`. The mapping is stated once in `citizens/domain/vocabulary.py` and summarized in
[Concepts](../organizers/concepts.md). A standalone Session lives in a container
`Assembly(kind="session")` created by `services/sessions.py`, because every storage path, ownership
check, retention sweep, export and report is keyed by `assembly_id`.

## Where to read next

* [Recording pipeline and reliability](recording-pipeline.md)
* [Transcription and analysis](transcription-analysis.md)
* [Jobs and background work](jobs.md)
* [Database and migrations](database.md)
* [Testing](testing.md)
