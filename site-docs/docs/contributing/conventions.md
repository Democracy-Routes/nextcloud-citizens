# Conventions and the gate

These are the code conventions, the checks to run before you push, and the release steps.

## Python

* **Lint:** ruff, line length 110, target Python 3.11 (`pyproject.toml`); rules `E`, `F`, `I`, `UP`, `B`. The runtime is Python 3.12.
* **Files** start with an SPDX header (`SPDX-License-Identifier: AGPL-3.0-or-later`).
* **Sync database access.** Endpoints that touch the database are `def`, not `async def`, so FastAPI runs them in its threadpool. The one async route, chunk upload, hands blocking work to `run_in_threadpool`.
* **No PATCH routes.** The AppAPI proxy forwards GET, POST, PUT and DELETE only, so partial updates use PUT. `tests/unit/test_proxy_verbs.py` fails the build otherwise.
* **No Nextcloud reads from a request.** Read provider configuration from the background-refreshed snapshot, never inside a transaction or a request.
* **Commit before long work.** Job handlers `commit()` before ffmpeg, speech-to-text or model calls. Do not hold SQLite's write lock across slow calls.
* **No unbounded body reads** on public routes, and **no blocking calls on the event loop**; both have guard tests.
* **Secrets never in logs or responses.** The logging redaction processor is defense in depth, not permission.
* **Comments say why, not what.**

## Database

* Schema changes need an **additive** Alembic migration in `citizens/db/migrations/versions/` with a working downgrade. Migrations run forward-only at startup. Prefer nullable or default-valued columns so upgrading never touches existing rows.

## Frontend

* Vue 3 with TypeScript. The built bundles in `js/`, `css/` and `recorder_static/` are committed and must match a fresh `npm run build`; CI fails on stale bundles.
* **Strings in five languages.** Every user-visible string goes into the catalogues for English, Italian, German, French and Spanish. Catalogues must define the same keys and placeholders; English literals are not allowed in templates or in the recorder.
* No fixed pixel font sizes (they would ignore the reader's font setting).
* Anything the phone does offline needs a Playwright spec in `tests/browser/`.

## Vocabulary

Say Assembly, Session, Table and Recorder in new product and API surfaces (the schema keeps `Round`); the software's assistant is the "AI assistant" and "facilitator" is only ever the person at the table; quotations are never "excerpts". See [Concepts](../organizers/concepts.md).

## The gate

Before pushing:

```sh
make lint && make test        # ruff; pytest in the app image; vitest
cd frontend && npm run typecheck && npm run build   # then commit the rebuilt bundles
make appstore-check           # if info.xml changed
```

For a release also run the browser suite (`make test-browser`) and the phone rehearsal. The CI workflow (`.github/workflows/ci.yml`) runs the lint and the tests, the production image against `scripts/image-smoke.sh`, the committed-bundle
check and the `info.xml` validation. A reliability feature lands together with a test that exercises its failure mode. See [Testing](../architecture/testing.md).

## Releasing

`make version VERSION=x.y.z` sets all version declarations at once (a test enforces they agree), then tag `vx.y.z`. CI builds the multi-arch image; the App Store step is separate. Details in [Updates and releases](../admin/updates.md).

## Documentation

Write in plain, precise English and keep claims traceable to the code. This site is built from `site-docs/` with `sh scripts/docs-build.sh`.

## License

AGPL-3.0-or-later.
