# Testing

Testing is part of implementation, not a final phase (brief §55).

## Layers

1. **Unit** (`tests/unit/`, pytest): pure logic — config, logging redaction,
   storage layout, migrations, and later token validation, state machines,
   chunk ordering/dedupe/checksums, provider normalization.
2. **Integration** (`tests/integration/`, from Milestone 1): API flows against
   a real app instance with a temp SQLite DB and mocked providers.
3. **Frontend** (`tests/frontend/`, vitest + happy-dom): components and the
   logic inside them, mounted without a browser — the wake lock, the polling
   primitive, error mapping, confirm semantics, the i18n catalogues. Fast
   enough to assert on a single component's behaviour, which Playwright is
   not.
4. **Browser** (`tests/browser/`, Playwright): the recorder driven for real in
   Firefox with a fake microphone, against a throwaway instance — network loss,
   reload recovery, a table's phone dying mid-round and another taking over,
   and clearing the phones at the end of an assembly.
5. **Manual gates**: real-phone recording tests over HTTPS (Milestones 2–3,
   brief §66) and the physical multi-phone room test before release (§57).

Roughly: 372 Python tests, 197 frontend tests, 5 browser tests. The first two
gate every commit and take about thirteen minutes together; the browser suite
is another seven and runs before a release.

## Running

```bash
make test           # both suites: pytest in the app image, vitest in node:22
make test-py        # only pytest
make test-frontend  # only vitest
make lint           # ruff
```

### Guard tests

Several tests exist to stop a whole class of defect coming back, rather than to
check one behaviour. They scan the source rather than run it, and each one
exists because the mistake had already been made:

* `test_no_config_reads_in_transaction.py` — provider config is an OCS call to
  Nextcloud; reading it inside a transaction holds SQLite's single writer slot
  across the network. Its docstring records the four times this happened.
* `test_no_long_work_under_the_write_lock.py` — the same rule for archives and
  PDF rendering, and ordering-aware, since doing that work *before* the first
  query is the fix rather than the bug.
* `test_no_unbounded_body_reads.py` — a public route must not buffer a body
  without a size limit.
* `test_no_blocking_on_event_loop.py` — blocking work in an `async def` handler
  freezes the whole server, not just that request.
* `tests/frontend/no-untranslated-recorder-strings.spec.ts` — no English
  sentence may reappear in the citizens' recorder.
* `tests/frontend/i18n.spec.ts` — the catalogues must define the same keys with
  the same placeholders, so a missing Italian string fails the build rather
  than surfacing on a phone.
* `tests/frontend/accessibility.spec.ts` — among other things, no fixed pixel
  font size, which would ignore the reader's own Nextcloud font setting.

Browser tests (release-blocker offline scenarios, brief §56 A and C):

```bash
make test-browser   # starts the instance, runs Playwright, stops it either way
```

or by hand, which is useful when iterating on one spec:

```bash
sh scripts/browser-test-env.sh start   # throwaway instance on 127.0.0.1:23100
cd frontend && npx playwright test device-replacement
sh ../scripts/browser-test-env.sh stop
```

These are the **only** tests that run the phone's own code — MediaRecorder,
IndexedDB, the join flow, the upload engine. The Python suite posts chunks the
way a phone would; the vitest specs mount components with the network mocked.
Neither would notice the recorder failing to start at all.

Two things to know when writing one:

* **A phone is a browser CONTEXT, not a second page.** `localStorage` and
  IndexedDB are per-context, so two pages would share the recorder session and
  the same audio store and fight over each other's state. `newPhone()` in
  `tests/browser/support/phone.ts` does this correctly.
* **Organizer calls do not go over HTTP.** Disabling the AppAPI middleware does
  not open those routes — nc_py_api then checks the request signature inline
  instead — so `organizerApi()` asks the container to make the call through the
  real router with the identity stubbed. See `citizens/devtools.py`.

Rebuild the frontend and restart the instance after changing recorder code:
the container serves the built bundle and runs without auto-reload, so source
edits are invisible until you do.

Notes: Chromium 151's `--use-fake-device-for-media-capture` no longer provides
a fake microphone on this host — the Playwright config uses **Firefox** with
`media.navigator.streams.fake`. The recorder accepts `?chunkms=2000` to speed
up chunking in tests.

Test F (10 concurrent devices):

```bash
sh scripts/browser-test-env.sh start
python3 tests/load/test_f_concurrent_devices.py   # prints PASS/FAIL
sh scripts/browser-test-env.sh stop
```

Provider tests that hit real APIs are opt-in only, gated on
`MISTRAL_API_KEY` / `DEEPGRAM_API_KEY` environment variables (Milestone 4+).
CI must never depend on paid APIs.

## Conventions

- `settings_env` fixture (tests/conftest.py) points `APP_PERSISTENT_STORAGE`
  at a pytest tmp dir and clears the settings cache.
- App instances for tests are built with `create_app(with_auth=False)` to skip
  AppAPI signature validation; auth logic itself gets dedicated tests.
- Every reliability feature (retry, dedupe, recovery) lands together with a
  test that exercises its failure mode.
