# Testing

Tests are written together with the code they cover. This page lists the layers, how to run them and the guard tests every change has to pass.

## Layers

1. **Unit** (`tests/unit/`, pytest): pure logic such as configuration, log redaction, storage layout, migrations, token validation, state machines,
   chunk ordering, deduplication and checksums, and provider normalization.
2. **Integration** (`tests/integration/`, pytest): API flows against a real app instance with a temporary SQLite database and mocked providers.
3. **Frontend** (`tests/frontend/`, vitest with happy-dom): components and the logic inside them, mounted without a browser.
4. **Browser** (`tests/browser/`, Playwright): the recorder driven for real in Firefox with a fake microphone against a throwaway instance. Network loss,
   reload recovery, a table's phone dying mid-round and another taking over, and clearing the phones at the end of an assembly. These are the only tests
   that run the phone's own code.
5. **Manual gates**: real-phone recording over HTTPS and the physical multi-phone room test before release (see [Before the day](../organizers/before-the-day.md)).

The Python and frontend suites gate changes; browser scenarios run before a release. CI must never depend on paid APIs: provider tests that hit real APIs are
opt-in, gated on `MISTRAL_API_KEY` and `DEEPGRAM_API_KEY`.

## Running

```sh
make test           # both suites: pytest in the app image, vitest in node:22
make test-py        # only pytest
make test-frontend  # only vitest
make lint           # ruff
make test-browser   # starts the instance, runs Playwright, stops it either way
```

Tests run inside the app container image (`citizens-test`, built with `WITH_TEST_TOOLS=1`), because the runtime is Python 3.12 there. To run the whole Python
suite quickly, `scripts/pytest-chunks.sh` spreads it across six containers against an rsynced snapshot of the tree (`sh scripts/pytest-chunks.sh` runs all six;
`sh scripts/pytest-chunks.sh 3 5` runs two; `LIVE=1` runs against the live tree).

Browser tests by hand:

```sh
sh scripts/browser-test-env.sh start   # throwaway instance on 127.0.0.1:23100
cd frontend && npx playwright test device-replacement
sh ../scripts/browser-test-env.sh stop
```

Run these only against the throwaway instance: `recording-safety.spec.ts` deliberately restarts `citizens-browser-test`.

## Guard tests

Several tests stop a whole class of defect from coming back. They scan the source rather than run it, and each exists because the mistake had been made:

* `test_no_config_reads_in_transaction.py`: provider configuration is an OCS call; reading it inside a transaction holds SQLite's writer slot across the network.
* `test_no_long_work_under_the_write_lock.py`: the same rule for archives and PDF rendering.
* `test_no_unbounded_body_reads.py`: a public route must not buffer a body without a size limit.
* `test_no_blocking_on_event_loop.py`: blocking work in an `async def` handler freezes the whole server.
* `tests/unit/test_proxy_verbs.py`: no PATCH route or client.
* `tests/frontend/i18n.spec.ts`, `no-untranslated-recorder-strings.spec.ts` and `accessibility.spec.ts`.

## Writing a browser test

* **A phone is a browser context, not a second page.** `localStorage` and IndexedDB are per context, so two pages would share the recorder session. Use
  `newPhone()` in `tests/browser/support/phone.ts`.
* **Organizer calls do not go over HTTP.** `organizerApi()` asks the container to make the call through the real router with the identity stubbed
  (`citizens/devtools.py`).
* The recorder accepts `?chunkms=2000` to speed up chunking.
* The Playwright config uses Firefox with `media.navigator.streams.fake`, because Chromium's fake device flag no longer provides a microphone on the build host.

## Conventions

* The `settings_env` fixture in `tests/conftest.py` points `APP_PERSISTENT_STORAGE` at a temporary directory and clears the settings cache.
* App instances for tests are built with `create_app(with_auth=False)` to skip AppAPI signature validation; authentication logic gets dedicated tests.
* Every reliability feature (retry, deduplication, recovery) lands together with a test that exercises its failure mode.

## Load tests

| Test | What it does |
|---|---|
| F | 10 concurrent devices (`tests/load/load_f_concurrent_devices.py`) |
| G | A single assembly, uploading a tone with captions off |
| H | A real half-hour assembly: 10 devices, real speech, real provider (`load_h_realtime_assembly.py`) |
| I | Ten tables on somebody else's instance, from the QR links alone (`load_i_remote_tables.py`) |
| J | A facilitated assembly |

!!! warning "Test H spends real money"
    It runs against the **live** instance and replays half-hour recordings at wall-clock speed, billing the provider for live captions, batch transcription
    and analysis. Run `--smoke` first (one device, about a minute), which proves the key and the whole path for pennies. `--yes` is required for the full run.
    It leaves a `TEST Carico ...` assembly behind and prints the command to delete it.

The first full run of test H (10 devices, 30 minutes) uploaded 1803 chunks with zero failures, peaked at 368 MiB while recording and 465 MiB
while transcribing, and showed that 512 MB is not enough for ten tables.

Test I needs no access to the server it measures: it replays real speech through the public routes from QR links, proving every table reached AUDIO_READY, that
the server's audio manifest hash equals the one computed from the bytes sent, and that an interrupted table's duration is the round minus the gap. It cannot press
"Start round" (the proxy authenticates organizer routes with a session cookie), refuses builds older than 0.6.2, and stops itself if the server starts failing.
