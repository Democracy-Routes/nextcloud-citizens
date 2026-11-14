# Frontend

There are two browser applications in `frontend/`, built with Vue 3 and Vite, plus translation catalogues.

## The organizer

`frontend/src/` (`App.vue`, `components/`) is the organizer single-page app. It follows Nextcloud's native app-shell pattern: a 300 px
navigation sidebar (assembly list with status dots, "+ New assembly", administrator-only Settings pinned at the bottom) beside a scrollable
content pane (assembly header and icon tabs). On screens up to 768 px the sidebar becomes an overlay drawer. Shared atoms are in
`components/ui/` (icons via `@mdi/js`, buttons, status pills, empty states, skeletons, confirm dialogs, toasts). Styles are ID-scoped tokens
over Nextcloud's CSS variables, adapting to its dark theme.

Tabs are grouped Plan, Run and Results: Overview, Rounds, Participants, Tables, QR codes, Live (monitor), Files, Analysis, Report, and
Results with Polis seeds. Settings has four tabs with a Save per card. In standalone mode the app serves its own organizer page, with
a landing and sign-in view.

In Nextcloud mode the bundle is loaded into the AppAPI embedded page by a script (`js/citizens-main.js`); its API base is derived from the
versioned bundle URL. The built output is committed: `js/`, `css/` and `recorder_static/` ship in the runtime image, and CI fails if they are
stale.

## The recorder

The phone recorder (`frontend/src/recorder/`) is a separate, dependency-light bundle served on PUBLIC routes at `recorder.html`. It has its own
dark, glanceable design (hero table number, pulsing record ring, iconised checklist, caption bubbles). It records with MediaRecorder, writes every
chunk to IndexedDB first and runs the sequential, backing-off uploader; it asks for the screen wake lock, sends heartbeats and keeps a client log
ring. See [Recording pipeline](recording-pipeline.md).

## Internationalisation

The interface is translated into five languages: English, Italian, German, French and Spanish.

* Shared catalogues for the phone recorder, participant pages and consent notice: `frontend/src/i18n/{en,it,de,fr,es}.json`.
* The organizer: one file per area in `frontend/src/i18n/organizer/` (`navigation`, `shell`, `setup`, `live`, `results`, `settings`), each in the five
  languages.
* The organizer follows the Nextcloud user's own language; the recorder and participant pages follow the **assembly's** language, not the
  phone's, because the phone is a shared table device. The server renders the consent notice, the event kit and the report in the assembly's
  language too (report strings in `services/report_text.py`).
* Guard tests keep catalogues honest: `tests/frontend/i18n.spec.ts` requires the same keys and placeholders in every language, and
  `tests/frontend/no-untranslated-recorder-strings.spec.ts` stops English sentences reappearing in the recorder, so a missing translation fails the
  build rather than surfacing on somebody's phone. Another guard forbids fixed pixel font sizes, which would ignore the reader's font setting.

## Building

```sh
cd frontend
npm run build            # organizer and recorder
npm run build:organizer
npm run build:recorder
npm run typecheck        # vue-tsc --noEmit
npm test                 # vitest run
```

Node 22 or newer is required. Recorder code changes need a rebuild and a restart of the test instance, because the container serves the built bundle.
