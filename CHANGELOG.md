# Changelog

All notable changes to Nextcloud Citizens.

## [Unreleased]

### Live-event hardening — 2026-09-01

A sweep through the whole app for things that could stop an assembly or lose
its record. Every fix has a test that fails without it.

**Things that could lose or block an event**

- **Downloading the audio no longer freezes every phone.** The export endpoints
  held SQLite's single write lock while copying every recording into a zip, so
  pressing "Download all audio" mid-event made each table's upload queue for up
  to a minute and then fail. Reads now use a session that takes no lock.
  Joining had the same shape — it asked Nextcloud for two settings while
  holding the lock, worst exactly when twenty tables scan their codes at once.
- **A phone that dies mid-round no longer loses its live transcript.** Caption
  sessions were only ever closed by a successful upload finishing, so a phone
  that never came back kept its session open forever: what it had already heard
  was never written down, and its transcription provider connection stayed open
  — and billable — until the container restarted.
- **A full disk no longer wedges a whole round.** A recording that failed to
  assemble was stuck in a state nothing could move it out of: it could not be
  re-recorded, abandoned or retried, and it blocked the round's cross-table
  analysis permanently. There is now a way out, and a **Retry** button once
  there is space again.
- **Re-running the analysis no longer destroys findings on failure.** It
  deleted the existing ones *before* calling the model, so a rotated API key
  meant a round that had twelve findings had none, with nothing regenerated.
- **Export archives are deleted with the audio they contain.** The retention
  sweep reported recordings purged while a complete copy of them sat in an
  export archive nothing ever reclaimed.

**On the phones**

- One bad moment on the venue WiFi no longer disconnects a table. Any failed
  status check used to discard the session and send the table back to the
  facilitator for a new QR code, and put the audio still on the phone out of
  reach.
- An armed phone stays awake. Only the recording screen held a wake lock, so a
  phone waiting for the facilitator went to sleep, showed as stale, and missed
  the round starting.
- A microphone failure no longer loops. It used to bounce the table back into
  the same round every five seconds with no way out; it now says what is wrong
  and offers a retry that works without reloading.
- The recorder no longer claims the server validated audio it never confirmed —
  and then offers to delete the phone's only copy.

**Italian, and being readable at all**

- **The recorder speaks the assembly's language.** There was no translation
  layer of any kind: a room of Italian citizens read English instructions, and
  tapped an English consent screen, to be recorded. The consent screen also now
  offers a way to decline.
- Pinch-zoom works. It was blocked outright, and the round's question — the one
  thing a table reads at arm's length — was the smallest text on the screen.
- Text follows the reader's own Nextcloud font size instead of fixed pixels,
  and touch targets meet the 44px minimum on touch devices.
- Dialogs can be used with a keyboard, messages are announced to screen
  readers, and icon-only buttons have names.

**Knowing what is going on**

- The Live tab shows when it was last updated, and says so when it cannot reach
  the server rather than leaving minutes-old numbers looking current.
- It also reads round state from the server rather than a stale snapshot, so it
  no longer offers to start a round that is already running.
- A failed table says *why* it failed and what to do about it, instead of an
  orange badge with a state name on it.
- Errors are sentences rather than "HTTP 500", and an unreachable server no
  longer produces an empty list that invites you to recreate work you already
  have.

**Destructive actions look destructive**

- The confirm dialog's red styling meant nothing: safe actions like publishing
  the report were red, and deleting an assembly was a small grey icon. Deleting
  an assembly now asks for its name; regenerating the QR codes, unpublishing
  and reopening a session ask at all.
- Re-running the analysis over findings a person has approved says how many it
  would destroy.

**Also**

- A public route can no longer be made to buffer an unbounded request body.
- A background job whose bookkeeping fails is rescheduled instead of being
  stranded until a restart.
- The QR sheet is downloaded rather than opened in a tab a pop-up blocker
  silently swallows.
- New guard tests scan the source for whole classes of defect — long work under
  the write lock, unbounded body reads, untranslated recorder strings, missing
  Italian keys, fixed pixel font sizes.

### Live captions are deleted when you delete things — 2026-08-31

- **Deleting an assembly left its live captions on the disk.** When captions
  started being saved two days ago, the file was filed by recording rather than
  by assembly — so the routine that erases an assembly's storage walked straight
  past it, leaving the text of what people said behind, with nothing left in the
  app able to reach or remove it. The same applied to deleting one table's
  transcript: the transcript went, the captions it was built from stayed.
  Both now go. No assembly has used captions-as-transcript yet, so nothing real
  was stranded.
- **The privacy note said live captions "are never stored."** True until the
  29th, not after. It now describes what is actually kept, where, for how long
  and what deletes it.
- The administration guide explains what the two transcription switches do in
  each combination, what captions-only costs you, and the Re-transcribe action.


### Live captions can be the transcript — 2026-08-29

- **Turning off "Final transcription" no longer throws the assembly away.**
  Before, leaving only live transcription on gave you captions during the round
  and then nothing at all: the captions were never saved, no transcript was
  produced, the analysis never ran, and the report came out empty — with nothing
  anywhere to tell you. Now the captions become the transcript, the analysis
  reads them, and the report is built from them as usual. The three working
  combinations are the ones you would expect: final only, live only, or both
  (where the final transcript is the record).
- This is worth choosing on purpose, not just a trap removed. Transcribing the
  finished audio a second time costs roughly ten minutes of processing per
  half-hour table, for text the server already worked out while listening. Live
  only skips it.
- **A report built from captions says so**, in the same methodology note that
  appears on the PDF, the Markdown, the organizer's screen and the participants'
  copy. Captions are made under time pressure and can miss speech, so a reader
  is told which kind of record they are holding.
- **"Re-transcribe" is now a button.** If the captions read poorly, one action on
  the Files tab transcribes that table properly from its stored audio and re-runs
  the analysis. This was possible before only by deleting the transcript first —
  through a dialog warning you about permanent erasure, which is the wrong thing
  to click when what you want is better text.
- **A caption engine that drops out mid-round no longer loses the first half of
  the transcript.** When a session failed and reconnected, the replacement began
  empty and overwrote everything recorded before the failure.
- Settings now explains what each combination of the two switches actually does,
  and warns plainly when neither is ticked — the one setting that still produces
  no record.

### Live captions now match the transcript — 2026-08-29

- **The captions on the phone disagreed with the final transcript even when
  both used the same model.** Not a model difference and not the audio: the
  live path was handing the recognizer ragged pieces of audio — a full frame
  then a 6-millisecond sliver, over and over — because it cut each block of
  decoded sound on its own instead of carrying the leftover into the next one.
  Vosk decides where one sentence ends on every piece it receives, so the
  ragged feed moved those boundaries and changed the words beside them,
  usually the harder ones: *livorno* became *limone*, *catalunya* became
  *taluno*. Measured on 800 seconds of a real assembly, the captions and the
  archived transcript agreed on 92.3% of words. They now agree on 98.9% —
  which is as close as it goes, because the recognizer is not perfectly
  repeatable: the identical audio sent twice agrees with itself 99.3%.
- **Captions that fall behind now say so.** When a transcription engine could
  not keep up, audio was quietly discarded and nothing was written to the log,
  so a gap in the captions was indistinguishable from a quiet room. The
  recording itself was never affected — it still isn't — but the loss is now
  recorded, with how many seconds went missing.
- Mistral live captions send audio in 480-millisecond pieces, the size Mistral
  documents, instead of one message per small block.

### A full room no longer freezes the server — 2026-08-29

- **Ten tables uploading at once brought the whole app to a standstill.** Not
  just slow — stopped: during a ten-table upload, a page that touches no data at
  all took 27 seconds and then gave up, the organizer interface stopped
  responding, and phones started getting errors as the database gave up waiting.
  Two of ten uploads finished in ten minutes. The cause was the upload handler
  doing its work in a way that let one phone's upload hold up every other
  request in the app, including the ones that had nothing to do with recording.
  The same ten tables now finish in 35 seconds with no request over 1.7 seconds,
  and the rest of the app stays responsive throughout.
- This was invisible to the existing load test, which ran ten devices in ten
  *separate* assemblies — which is not a room. `tests/load/load_g_single_assembly.py`
  puts all ten in one assembly and releases them together, the way a facilitator
  starting a round does.

### Revoke now reaches every phone — 2026-08-29

- **"Revoke access" could leave phones connected.** If you had regenerated the
  QR sheet at any point — printing a replacement for a lost code, say — the
  tables that were already recording kept working afterwards, which is correct
  and deliberate. But revoking then only disconnected devices holding a *current*
  code, so those same tables were the ones it skipped: the organizer pressed the
  emergency stop and the phones already in the room kept their access for the
  rest of the day. Revoke now disconnects every device on the assembly, which is
  what the button has always said it does. Found by writing the negative
  authorization tests, not in the field.

### Deploys now actually reach your browser — 2026-08-28 (v0.6.0-beta.11)

- **The organizer interface could keep showing the previous build for an hour
  after an update.** Nextcloud's app proxy adds an hour of browser caching to
  anything that does not set its own rule, and the interface files are served
  from addresses that never change — so nothing told the browser a new version
  existed. The recorder page never had this problem because it stamps a version
  onto its files; the organizer interface never got the same treatment.
  It does now: the browser checks for a new build on every load, and still
  reuses the file when nothing changed.


### Wrong report on a phone, Vosk crash, Settings polish — 2026-08-28 (v0.6.0-beta.10)

- **A phone could download another assembly's report.** Not a mistake on your
  part: Nextcloud's app proxy adds an hour of browser caching to any download
  that does not set its own cache rule, and the report URL is identical for
  every assembly — only the session token tells them apart, and caches do not
  read tokens. A device used in two assemblies served the first one's PDF for an
  hour. All downloads now refuse to be cached. The same fault also returned a
  stale report to organizers after approving findings, and stale audio after
  deleting it.
- **Vosk crashed when two tables recorded at once.** A lock created at the wrong
  moment failed only when two connections needed a model simultaneously — which
  is every real assembly. It passed every earlier test because one connection
  never contends. `scripts/vosk-check.sh` now reproduces exactly that.
- **Live and final transcription are now laid out the same for every engine**,
  as two aligned columns with the headings above the model fields, instead of
  three different vocabularies and no alignment.
- **The QR sheet is a proper PDF.** Printing from the browser silently dropped
  every page after the first, so ten tables printed as four. The Print button
  now downloads a sheet with four codes per page, cut lines, and the join link
  under each code for a phone that cannot scan.


### Settings in tabs, and Vosk models by name — 2026-08-28 (v0.6.0-beta.9)

- **Settings is now three tabs** — Audio, AI analysis, General — instead of one
  long scroll. One Save still saves everything, and switching tabs never loses
  what you typed.
- **Every engine now separates the two jobs clearly**: "Live captions
  (provisional)" and "Final transcript (canonical)", with the model for each.
  Whisper gained its live-model field, which the server already supported but
  the page never showed.
- **Vosk lists all five assembly languages**, each with a live and a final
  model. A blank final reuses the live one; a language you have not set up uses
  the server default, so a half-filled table never blocks a transcript.
- **Vosk models are named, not paths.** Settings holds
  `vosk-model-small-it-0.22`, so switching model is editing that name.
- **Models are downloaded only when you want them** — `scripts/vosk-model.sh
  <name>` — and the server now **frees a model once it has been idle**, keeping
  one at a time. An assembly uses one language, so an idle server costs a few MB
  instead of holding a few hundred overnight. A model in use is never unloaded,
  however long the round runs.


### A Vosk model per language — 2026-08-27 (v0.6.0-beta.8)

- **Vosk can now use a different model for each language**, which is how Vosk
  works: unlike the other engines it has no single multilingual model. Set one
  server URL and a row per language in Settings, and the language you choose for
  an assembly selects the model — for both the final transcript and live
  captions. A language with no row still transcribes, using whatever model the
  server started with.
- **`scripts/vosk-up.sh` runs a Vosk server on your own machine** with Italian
  and English models, prints the exact settings to paste in, and needs no
  internet access at recording time. One server holds every language.


### Fixed: Settings lockout and upload errors — 2026-08-27 (v0.6.0-beta.7)

Two regressions from yesterday's release, and the underlying cause of both.

- **Settings is accessible again.** The administrator check added yesterday
  called a Nextcloud method that does not exist, so it failed for everyone and,
  because it fails closed, silently removed Settings from real administrators.
  It now asks Nextcloud for the signed-in user's own groups — the one call an
  app of this kind is permitted to make. Verified against a live server for
  both an administrator and a non-administrator before shipping.
- **A broken check can no longer hide Settings without saying so.** Only a
  definite "you are not an administrator" removes the entry; any other failure
  leaves it visible so the error is on screen instead of invisible.
- **Recording phones no longer see spurious "Network unavailable".** Uploads
  were occasionally failing with a server error, which the phone reported as a
  lost connection. No audio was ever at risk — the upload retried and
  succeeded — but people were sent to check WiFi that was working. The phone
  now distinguishes a server problem from a network problem and says so.
- **The cause: the retention sweep held the database's single write slot while
  waiting on Nextcloud**, once a minute, so an upload arriving at the wrong
  moment timed out. Configuration is now read before the database is touched,
  here and on the recording upload path, and the two other places that did the
  same thing during transcription and analysis.
- **Polling no longer competes with recording.** Caption and status polls took
  the write lock even though they only read, and every request wrote a
  "last seen" timestamp. At twenty tables that was roughly twelve write-locks a
  second for bookkeeping. Both are gone.
- A build-time check now fails if any background work reads configuration
  inside a database transaction. This bug class had appeared three times and
  been fixed with comments each time.


### Integrity, retention and consent — 2026-08-27 (v0.6.0-beta.6)

Second of four rounds of production-readiness work.

- **One dead phone no longer wedges a whole round.** A table whose phone died
  mid-upload left its recording waiting for chunks that were never coming, and
  the round's cross-table analysis waited with it — indefinitely, with no
  action that could resolve it. Stalled uploads are now given up on
  automatically, and an organizer can stop waiting immediately from the Live
  tab. The audio already received is kept and the table can re-record.
- **Storage no longer grows without limit.** Upload chunks were kept forever
  alongside the assembled recording, so every assembly occupied twice the disk
  it needed. They are now reclaimed once the assembled audio is verified, with
  each chunk's checksum retained as the audit trail.
- **Audio retention.** Settings now has a retention period in days, counted
  from when an assembly is closed, with a per-assembly override. It deletes
  **audio only** — transcripts, findings and reports are the record of the
  assembly and are never touched. Deletion is audit-logged.
- **The server refuses writes when the disk is nearly full** instead of failing
  halfway through one. Phones keep their audio and keep retrying, as they do
  for any other outage.
- **Tables are told what happens to the recording, before it starts.** A new
  screen names the transcription engine, says whether it is an outside service
  or the organisation's own server, states how long audio is kept, and explains
  that speakers are labelled only "Speaker 1", "Speaker 2". The text is
  generated from the live configuration, so it cannot drift from the truth.
- **`docs/privacy.md` now describes what the software actually does.** It had
  claimed configurable retention and a consent screen that did not exist. Both
  exist as of this release; the remaining gaps are stated plainly rather than
  implied away.
- **Security:** administrator settings now verify administrator group
  membership in the app, not only at the proxy; revoking invites disconnects
  devices that already joined, instead of leaving them working for up to 16
  hours; QR invites expire after 30 days; and provider endpoints must be real
  http/ws URLs.
- Deleting an assembly now also deletes the phones' diagnostic logs, which
  previously survived as orphaned files.

### Surviving a real assembly — 2026-08-27 (v0.6.0-beta.5)

First of four planned rounds of production-readiness work. Everything here is a
failure that only appears at full scale or when something else breaks, which is
why none of it showed up in testing with a handful of tables.

- **Every table can now join.** The join limit was 10 attempts per minute *per
  IP address* — but at a venue every phone shares one address, so from the 11th
  table onward people scanning their QR code got "Too many requests" and a dead
  error screen. The budget now belongs to the invite token, so each table has
  its own, and the phone retries a busy server instead of giving up.
- **The limit can no longer be sidestepped.** It trusted a header the client
  sends, so anyone could reset their own budget. It now uses the address the
  Nextcloud proxy supplies, which a client cannot forge.
- **A failed transcription no longer disappears.** When an engine failed
  temporarily, the error state was rolled back with the retry — so once retries
  ran out the recording sat under an "in progress" spinner forever, with nothing
  working on it. Failures are now recorded, visible, and retryable.
- **Recordings stuck mid-analysis can be recovered** from the Analysis tab, and
  a stuck transcription now offers a retry button in the Live tab. Previously
  the only way out was editing the database by hand.
- **Security: testing a provider connection no longer leaks the saved key.**
  Naming a different endpoint without also entering a key made the server send
  the *stored* key to that address. A typed-in URL now requires a typed-in key.
- **Uploads no longer block each other.** Each chunk upload held the database's
  single write slot while reading the upload off the network, so one phone on
  weak WiFi could stall every other table until requests failed. The upload is
  read first now.

### Fixed: Approve and Reject returned HTTP 405 — 2026-08-26 (v0.6.0-beta.4)

- **Reviewing an AI finding now works.** Approve, Reject and Save-&-approve
  failed with a red `HTTP 405`. The cause was not in this app: AppAPI's proxy
  registers handlers for GET, POST, PUT and DELETE only, so the PATCH request
  was rejected by Nextcloud's router and never arrived. All partial-update
  endpoints now use PUT.
- **Two more repairs that came with it.** Editing an assembly (Overview tab)
  and editing or reordering rounds (Rounds tab) used the same verb and had
  never worked through the proxy either.
- New `tests/unit/test_proxy_verbs.py` fails the build if any route or client
  uses a verb the proxy cannot forward, or if `info.xml` stops declaring a verb
  the API actually uses — the existing suite could not catch this, because it
  drives the app directly and bypasses the proxy that does the rejecting.

### Live captions for every engine — 2026-08-26 (v0.6.0-beta.3)

- **Live captions are no longer Deepgram-only.** Every configured engine now
  produces them through the protocol it actually speaks: Vosk and
  Deepgram-protocol servers stream natively, **Mistral Voxtral Realtime** is
  wired up at last (it was marked "not yet active" since the beginning), and
  Whisper endpoints caption from rolling 20-second windows, which works with
  any OpenAI-compatible server rather than only those implementing a realtime
  socket.
- **The Deepgram caption endpoint is configurable**, so a self-hosted server
  speaking the same streaming protocol (WhisperLiveKit) can provide captions
  without audio leaving your network.
- **Captions now update as people speak.** Engines only finalise text at a
  pause, so a table talking continuously used to see nothing; in-progress
  speech is now shown provisionally and replaced by the final wording.
- New: one ffmpeg per recording decodes the phone's chunk stream to PCM for the
  engines that need it (Deepgram takes the stream as-is). Caption failures
  still never touch the recording.

### Whisper and Vosk speech-to-text — 2026-08-26 (v0.6.0-beta.2)

- **Whisper through any OpenAI-compatible endpoint**: OpenAI's hosted API, or a
  server you run yourself (Speaches, whisper.cpp, LocalAI, vLLM, WhisperX).
  Configure a base URL, a model and an optional key. Servers that add speaker
  labels — WhisperX-style, or OpenAI's `gpt-4o-transcribe-diarize` — are used
  in diarized mode automatically; plain Whisper returns transcripts without
  speakers, which the Settings page states plainly.
- **Vosk**: fully offline transcription against your own vosk-server over its
  WebSocket protocol. No key, no internet. Returns word timings but lower-case
  text without punctuation and no speaker separation.
- **Audio can now stay on your infrastructure.** With a self-hosted Whisper
  server or Vosk, recordings are never sent to a third party; the store listing
  and privacy notes say so, and the Ethical AI Rating is green in that setup.
- Reports no longer claim "speaker diarization" when the transcript has no
  speaker labels.
- Fixed three places where a newly added provider would silently have been
  handed Mistral's API key (`batch_transcription_ready`, `live_stt_snapshot`)
  or shown Deepgram's settings panel (the Settings `v-else` branch).
- Test and dev container images no longer share a tag, so building the dev
  image can no longer strip the test tooling.

## [0.6.0-beta.1] — 2026-08-25

First release prepared for the Nextcloud App Store. Everything below is in
addition to the assembly, recording, transcription, analysis and reporting
features built up to 0.5.2.

### Packaging
- **The runtime image is now self-contained.** It previously omitted `css/` and
  `recorder_static/`, which worked only because development bind-mounts the
  source over the image — a clean deployment would have served an unstyled
  organizer UI and a dead phone recorder.
- Store metadata completed: `<docker-install>` pointing at
  `ghcr.io/theragehero/citizens`, SPDX licence identifier, repository,
  documentation and screenshot links, and a plain data-processing disclosure
  naming what leaves the server and when.
- Added `LICENSE` (AGPL-3.0-or-later) and SPDX headers across the sources.
- One command sets the version everywhere it is declared (`make version`), with
  a test that fails if the six declarations drift apart.
- `make appstore` packages the signed-release archive; `make appstore-check`
  validates `info.xml` exactly the way the store does (XSLT, then schema).
- GitHub Actions: lint + tests, a check that the committed frontend bundles
  match their sources, multi-arch (amd64/arm64) image publishing, and the
  App Store release.

### Hardening
- The container runs as a non-root user, declares a healthcheck, binds all
  interfaces by default, and no longer ships test tooling or the dev seeding
  helper.
- `CITIZENS_INSECURE_NO_AUTH` is now ignored unless Nextcloud is a loopback
  address, so a stray environment variable cannot disable authentication on a
  real deployment.
- Missing `APP_SECRET` or `NEXTCLOUD_URL` is reported in the log and in
  `/api/v1/health` instead of failing silently later.
- Dependencies carry upper bounds so rebuilding a tag stays reproducible.

### Documentation
- Administration guide, contribution guide and security policy; the README is
  written for administrators; the development doc no longer describes a private
  server.

### QR sheet copy button fix — 2026-08-25 (v0.5.2)

- Fixed the oversized copy icon on the QR codes tab: a stylesheet rule meant
  for the QR image was stretching every icon in the card, including the new
  button's. The copy control is now a normal compact "Copy link" button under
  each code.

### Delete transcripts from the Files tab — 2026-08-25 (v0.5.1)

- **Delete transcript** next to Delete audio: per table and for the whole
  session. The verbatim text is erased everywhere — transcript, raw provider
  JSON on disk, and the quotes inside findings, including in an already
  published report (the frozen copy is re-created without them).
- Findings and AI summaries **survive** the deletion; where quotes used to be,
  reports now say "Evidence removed with the transcript" instead of showing a
  finding that merely looks unsupported.
- When the audio is still on the server, deleting a transcript returns the
  recording to "audio ready" so it can be **transcribed again** (useful to redo
  a poor transcript or switch model).
- Fixed a pre-existing silent data loss: re-transcribing a recording already
  replaced its transcript and stripped approved findings of their evidence with
  no trace — those findings are now flagged the same way.

### Closing a session, Files tab, interim vs final report — 2026-08-25 (v0.5.0)

- **A report is now interim until you close the session.** The Report tab says
  so plainly ("Interim report — 1 of 3 tables have completed all rounds") and
  the PDF/Markdown/JSON downloads stay disabled until then. Closing creates the
  **final report** (stamped FINAL with a "N of M tables contributed" coverage
  line), stops phones from recording, and runs a last analysis pass over the
  tables that did participate. Reopening is possible for a late table.
- **The published report freezes at closing**: participants keep reading the
  version from when you closed, even if you reopen the session and new content
  arrives. Closing again republishes the updated version.
- **New Files tab per assembly**: every table's audio with duration, size and
  state; download one table, download all audio as a ZIP, or **export the full
  session** (manifest with checksums, audio, transcripts, findings and the
  report — portable to another server). Audio can be deleted per table or for
  the whole session **without deleting the session**: transcripts, findings and
  the report are kept.
- **QR sheet**: a proper "Copy link" button per table replaces the tiny icon.
- Fixed: assemblies stayed "Draft" forever in independent mode — the status now
  moves to Active on the first recording and Complete when closed.

### Independent mode: auto-advancing rounds, table summaries, auto-report — 2026-08-25 (v0.4.1)

- **Rounds advance automatically per table**: when a round's planned time
  elapses the phone finishes on its own (15 s "Keep talking" grace), and
  after any finish — timed or manual — it advances to a break-friendly
  "We're ready — Start Round N" prompt showing the next question. Recording
  starts only on that tap.
- **The table sees its own results**: after the last round, the phone shows
  that table's AI summary for each round as analysis completes.
- **The report reaches phones in two cases**: automatically once EVERY table
  has completed EVERY round (independent assemblies; with analysis enabled
  the summaries must be ready so the report is never empty), or the moment
  the organizer clicks Publish. Managed assemblies stay publish-only.
  Verified live end-to-end with a 1-minute timed round.

### Round-end 500 fix + managed flow + institutional reports — 2026-08-24 (v0.4.0)

- **Fixed the round-end HTTP 500** ("database is locked"): background jobs held
  the SQLite write lock across minutes-long ffmpeg/transcription/analysis
  calls, starving the phones' finish requests. Jobs now release the lock
  before external work; verified live with zero failures across 204 status
  requests hammered through a full processing chain.
- **Phones never dead-end**: transient server errors auto-retry with backoff
  ("busy server" note), and a failure screen gains a Try again button. The
  done screen keeps the table armed for the organizer's readiness count.
- **Managed flow end-to-end**: after ending a round the Live tab shows a
  one-click "Start Round N+1" banner (and an "all rounds done" pointer);
  when the organizer publishes the report, phones auto-open it after a 3 s
  countdown.
- **Institutional PDF**: branded header with organization logo + name (new
  Settings fields), generation date, executive summary of all rounds,
  grouped findings with colored type badges, evidence quote bars, running
  footer with page numbers.
- **Consensus/divergence vocabulary** everywhere (report, analysis tab,
  phones): Proposals · Points of consensus · Points of divergence ·
  Concerns raised · Open questions · Minority positions · Emerging ideas;
  the AI prompts now actively hunt for conflicts within and between tables,
  naming both sides.
- **Per-assembly AI instructions** (wizard + Overview) appended to the global
  admin instructions.
- Settings shows only the selected transcription provider's fields.
- **Deleting an assembly now deletes its audio files** (chunks, canonical
  audio, transcripts, exports) along with the database records.

### Reports round — 2026-08-24 (v0.3.0)

- **PDF reports** with the organization logo on the header (logo uploadable in
  Settings, PNG/JPEG up to 1 MB), alongside Markdown and JSON.
- **Publish report to tables**: a new button on the Report tab makes the
  report (approved findings + AI summaries only — never drafts) visible on
  the recording phones, which get a "View assembly report" screen with a
  PDF download. Unpublish anytime.
- **QR codes re-viewable anytime**: invite links are now stored encrypted
  with the app secret, so the QR tab always shows the printable sheet again
  (join verification still runs on hashes; a database dump alone reveals
  nothing). Codes issued before this release still need one regenerate.
- **Custom AI instructions**: Settings gains an "Additional analysis
  instructions" field appended to the built-in prompts (shown read-only for
  reference); the JSON output contract and mandatory evidence links cannot
  be overridden.
- Wizard and round form fields now stretch to full width; device ages on the
  Live tab read "3m ago / 11h ago" instead of thousands of seconds.
- Settings remains admin-only (enforced at the Nextcloud proxy; the nav item
  hides for non-admins). Assemblies stay private per organizer account.

### Recorder polish round — 2026-08-24 (v0.2.0)

- **Nextcloud-style recorder**: the phone recorder now uses the same light
  Nextcloud design language as the organizer app (white cards, NC blue,
  red reserved for recording state).
- **Live transcript**: visible by default (collapsible), and consecutive
  captions from the same speaker flow together as one paragraph with a
  "Speaker N" label — a new bubble starts only when the speaker changes
  (Deepgram live diarization).
- **One-tap start for independent assemblies**: mic check, round choice and a
  single red "Start recording" button on one screen — the READY step now
  exists only in orchestrated mode (where it arms the table).
- **Recording screen**: the round question stays pinned at the top (tap to
  expand), and the technical status shrank to a discreet one-line strip
  (tap for details). Alerts (storage error / offline) remain full-size.
- **Recovery dead-end fixed**: when the server definitively no longer has a
  recovered recording (deleted/reset assembly), the phone now explains it and
  offers "Download audio file" and an explicitly confirmed "Delete local
  audio" instead of retrying forever.
- **QR sheet**: tidier copy-link row under each code (truncated URL + copy
  icon). Organizer app no longer hides its bottom edge behind mobile browser
  toolbars (dynamic viewport height).
- Round-end auto-stop on phones now reacts within ~5 s; app version 0.2.0
  busts cached recorder assets so phones pick the new UI up immediately.

### Recording modes, summaries, model split, auto-QR — 2026-08-24

- **Two recording modes per assembly** (wizard choice): *Orchestrated* — tables
  arm with one READY tap, then recording starts and stops automatically for
  everyone when the facilitator starts/ends the round (15 s cancellable
  finish countdown; Live tab shows "N/M tables ready" with a warning before
  starting incomplete); phones can no longer record outside an active round.
  *Independent* — each table records the shared questions on its own schedule
  (even days apart); cross-table clustering re-runs incrementally as tables
  complete. Verified live end-to-end (arm → auto-start → auto-finish → sync).
- **AI summaries everywhere**: every analyzed table now gets a mandatory
  neutral 2–4 sentence summary (plus findings when substantive), rounds get a
  cross-table overview; both appear in the Analysis tab and reports, clearly
  labeled AI-generated. test4's small-talk session now reads "The table
  participants introduced themselves…" instead of an empty tab.
- **Separate live/final transcription models** for both Deepgram and Mistral
  in Settings (legacy single-model settings still honored).
- **QR codes generated by default**: creating an assembly generates all table
  codes immediately and lands on the printable sheet.

### Recorder app-shell — 2026-08-24

- The phone recorder now behaves like a native app: page scrolling and
  overscroll-bounce are fully locked (fixed 100dvh shell, no pinch-zoom or
  double-tap zoom), each screen is header + internally-scrollable middle +
  pinned action bar with safe-area padding — READY / Start / Finish are
  always on screen, even with the live transcript panel open.


### Milestones 6 + 7-lite — 2026-08-24 (AI analysis, reports, recorder lock, GitHub)

- **AI analysis pipeline**: after transcription, each table is analyzed by the
  configured OpenAI-compatible endpoint (verified live against Ollama Cloud /
  deepseek-v4-flash): strict-JSON extraction validated by Pydantic with
  correction retries; findings without real transcript evidence are dropped;
  once every table of a round is analyzed, cross-table clustering runs
  automatically ("Mentioned at N tables" — never support percentages).
  Findings are DRAFTs with mandatory human review (approve / reject / edit →
  EDITED_AND_APPROVED; original AI output preserved for audit).
- **Analysis tab** (review UI with evidence expanders, re-run, guided empty
  states) and **Report tab**: assembly report from approved findings
  (optional clearly-marked drafts), evidence quotes with timestamps, fixed
  AI-assistance methodology note, Markdown + JSON downloads.
- **Recorder lock**: after a table's recording is synchronized the device is
  locked on a completion screen — no way back to start a stray recording; the
  server refuses a second healthy recording per table+round (409); the next
  round appears automatically when the facilitator starts it; failed attempts
  (invalid/incomplete audio) still allow re-recording.
- Published to GitHub: https://github.com/theRAGEhero/nextcloud-citizens
  (public; tracked files and full history verified clean of secrets).
- 54 backend tests; Playwright offline tests green; full chain verified live
  end-to-end including a real cross-table finding.

### UI/UX design round — 2026-08-23

- Organizer rebuilt around Nextcloud's native app-shell: sidebar navigation
  (assembly list with status dots, admin Settings), content pane with
  assembly header, icon tabs and a new Overview tab (stat cards + state-aware
  "next step" guidance). Design system in `frontend/src/components/ui/`:
  MDI icons, buttons, status pills, empty states, skeleton loaders,
  confirmation modals for destructive actions, toasts. Full dark-theme and
  mobile support; conversation-style transcript view; countdown bar with
  progress in the Live tab; refined printable QR sheet.
- Recorder redesigned: hero table number, pulsing record ring around the
  timer, iconized pre-flight checklist and status rows, caption bubbles,
  animated success state.
- Fixed a real M4 regression the screenshot audit caught: the phone's
  completion poll only accepted AUDIO_READY and hung when auto-transcription
  advanced the state within seconds — it now accepts every post-validation
  state.
- Verified: screenshot audit (light/dark, desktop/mobile, all screens),
  Playwright offline tests A & C, 47 backend tests, typecheck clean.
  Organizer bundle +13 KB gzip, recorder +3 KB.

### Milestone 4 — 2026-08-23 (STT: batch + live)

- Batch transcription pipeline: after audio validation, recordings are
  automatically transcribed by the configured provider (Deepgram `nova-3`
  with `diarize_model=latest` + utterances; Mistral Voxtral
  `voxtral-mini-latest` with `diarize` — model IDs verified against provider
  docs 2026-08-23 and admin-configurable). Normalized transcript schema
  (SPEAKER_NN by first appearance, segments + word timestamps), raw provider
  JSON retained on disk, durable TRANSCRIBE_FINAL job with temporary-error
  retry and permanent-error surfacing, organizer transcript API + manual
  (re)transcribe, transcript panel in the Live tab.
- Provisional live captions: the phone's safety chunks are forwarded into a
  server-side Deepgram streaming session (zero extra phone bandwidth);
  recorder "Show live transcript" panel, clearly labeled PROVISIONAL;
  failures cool down instead of reconnect-looping and never affect
  recording. Mistral Voxtral Realtime not yet wired (captions report
  unavailable with Mistral).
- Settings: STT model fields per provider; "Test connection" now tests the
  key typed in the form before saving (the reported "No API key configured"
  confusion). Deepgram key stored (encrypted) and verified live; full
  speech → chunked upload → assembly → automatic Deepgram transcription with
  diarization verified end-to-end on the production server, live captions
  included. 52 tests.

### Fix round + platform upgrade — 2026-08-23

- **Recorder CSP fix**: the page moved to `/recorder.html` and ships its own
  Content-Security-Policy — Nextcloud's proxy applies `default-src 'none'`
  (no script allowance) to proxied ExApp pages and only an ExApp-provided CSP
  header survives. Mic-test playback via WebAudio (blob: media is blocked).
  Old `/recorder/` QR links require regeneration (proxy follows redirects
  internally). Live join → record → synchronize verified in a headless
  browser against the production URL.
- **QR codes** render with a viewBox (no more clipping); printable sheet kept.
- **Organizer layout**: opaque Nextcloud-style app surface, ID-scoped styles
  (NC core `button:not()` chains override plain classes), underline tabs,
  fixed accessible danger red, full-width surface, recorder asset cache
  busting via app version.
- **Admin Speech & AI settings**: sensitive AppConfig key storage (hint-only
  responses), STT provider choice, live/final toggles, OpenAI-compatible
  analysis endpoint (Ollama-ready), connection tests, audit trail. 37 tests.
- **Nextcloud upgraded 32.0.0 → 33.0.8 → 34.0.3** (user-approved): per-hop
  DB dumps + code-volume backup + rollback doc in
  `/root/backups/nextcloud-upgrade-20260823/`; app_api auto-updated to 34.0.0;
  Citizens ExApp registration survived both hops; full live recording
  round-trip re-verified on 34.

### Milestone 3 — 2026-08-23

- Offline resilience: exponential-backoff upload retry with online-event
  wake and manual retry; reload/crash recovery (IndexedDB scan → "Recovered
  recording" → resume synchronization); storage monitoring with low-space and
  write-failure alerts; explicit local cleanup of synchronized recordings.
- Device heartbeats (20 s) + client log shipping to the server (offline-
  tolerant, per-session JSONL); facilitator "Live" dashboard tab with round
  start/end controls, per-table device/upload/local-safe status and device
  log viewer.
- Round lifecycle (start/end, single-active enforcement); recorder prompts
  to finish when the facilitator ends the round.
- SQLite `BEGIN IMMEDIATE` transactions — fixes "database is locked" under
  concurrent device uploads.
- Release-blocker tests all passing: §56 Test A (network loss) and Test C
  (reload recovery) as Playwright browser tests with a fake microphone
  (Firefox), Test D/E in pytest, Test F (10 concurrent devices) as a load
  script. 31 backend tests total.

### Milestone 2 — 2026-08-23

- Public recorder API: invite-token join → short-lived scoped recorder session
  (hash-only bearer), start recording, chunked upload (raw octet-stream,
  SHA-256 verified, idempotent on recording+sequence+hash), complete with
  server-side missing-chunk detection and resend, status polling. Join
  endpoint rate-limited.
- Recording state machine (§24) with explicit resumable transitions; durable
  SQLite job runner (claim/retry/backoff, stale-RUNNING recovery on restart);
  ASSEMBLE_AUDIO job: concat → ffprobe validate → ffmpeg remux → canonical
  file + checksum + manifest.json.
- Recorder phone SPA (separate PUBLIC bundle, no Nextcloud chrome): QR join
  (secret stripped from URL), pre-flight checks (mic, formats, IndexedDB,
  persistence, connectivity, level meter, 5-s test), recording screen with
  IndexedDB-first chunk pipeline, upload/pending status, offline banner,
  wake lock, finish → synchronize → server-validated done state.
- 28 tests total; recorder integration suite uses real opus audio through the
  real assembly pipeline and covers duplicate upload (Test D) and missing
  chunk (Test E). Live HTTPS end-to-end verified on the dev server
  (join → upload → AUDIO_READY, duration validated).

### Milestone 1 — 2026-08-23

- Assembly core backend: assemblies, rounds (add/edit/reorder/delete), tables,
  participants (manual + CSV import, anonymous labels), random table
  assignment, copy-from-previous-round, manual moves. Ownership authorization
  (creator-scoped; missing and not-owned both answer 404).
- Recorder invites: 256-bit tokens (SHA-256 hash stored only), QR SVGs
  (segno) returned exactly once at generation, revoke/regenerate, audit
  events. Invite URLs carry the token in the URL fragment.
- Organizer SPA: Vue 3 + TypeScript + Vite (single IIFE bundle into `js/` +
  `css/`) — assembly list, creation wizard, rounds/participants/tables/QR
  tabs, printable QR sheet. Nextcloud theming via CSS variables.
- 17 tests incl. an integration suite covering the 50-participant/10-table/
  2-round acceptance flow; fixed a SQLite self-deadlock (audit writes now use
  the request session).

### Milestone 0 — 2026-08-23

- ExApp skeleton: FastAPI + nc_py_api (heartbeat/init/enabled), SQLite with
  WAL + foreign keys, first Alembic migration (audit_events), structured
  logging (structlog: dev console + rotating JSONL, secret redaction,
  request-ID correlation), `/api/v1/health`.
- Registered on the live Nextcloud via an AppAPI manual-install daemon;
  "Citizens" top-menu entry renders the M0 shell with live health data for
  `citizens-test`.
- Dev workflow: `make up` (auto-reload container, 512 MB cap), `make register`,
  `make test`/`make lint` (run inside the container image — the host is too
  memory-constrained for a native venv), `make dev-reset` (Citizens data only).
- Verified AppAPI route access control end-to-end; documented non-obvious
  AppAPI behaviours (numeric access levels in `--json-info`, no-leading-slash
  route regexes, session-only proxy auth, `/apps/app_api/proxy/` URL form) in
  `docs/architecture.md`.

### Phase 0 — 2026-08-23

- Inventoried the development server (Nextcloud 32.0.0.13, AppAPI 32, clean
  ExApp slate); documented in `docs/development-environment.md`.
- Created and restore-tested a pre-Citizens Nextcloud backup (DB + config +
  custom_apps + compose): `/root/backups/nextcloud-pre-citizens-20260823/`.
- Repository baseline: README, docs, changelog, gitignore.
