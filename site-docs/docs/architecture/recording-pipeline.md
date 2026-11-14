# Recording pipeline and reliability

Audio is the primary record. Captions, transcription and analysis are not a substitute for it. The pipeline
reduces recoverable failure modes; it cannot guarantee capture through a dead battery, a killed browser, a lost
microphone, failing hardware or erased browser storage.

## From microphone to AUDIO_READY

```text
PHONE (recorder SPA, PUBLIC routes)          SERVER
MediaRecorder (~10 s timeslices)
  +-> IndexedDB FIRST (chunk + sha256)  -->  POST chunks/{seq} (octet-stream,
       +-> uploader: sequential, exp.         X-Chunk-SHA256 verified,
          backoff, online-event kick,        idempotent on rec+seq+hash)
          manual retry                          +-> AudioChunk row + file
  +-> oversized on 413 --> POST parts/ (1 MiB slices) --> finalize assembles
finish -> complete(total)              -->  gap check -> resend missing -> job
                                            ASSEMBLE_AUDIO: concat -> ffprobe
                                            -> ffmpeg remux -> sha256 -> AUDIO_READY
heartbeat every 20 s                   -->  recorder_sessions.last_status_*
client log ring (IndexedDB)            -->  logs/devices/<session>.jsonl
```

The phone first commits each original MediaRecorder chunk to IndexedDB. Upload acknowledgements do not delete it.
Normal chunks use the chunk route; oversized chunks, or uploads rejected with HTTP 413, use 1 MiB parts. The server
stores immutable part metadata and checksums, flushes the bytes and directory entries, and commits its receipt before
acknowledging them. A retry asks which parts are present and resumes. SQLite runs with `synchronous=FULL` for durable
receipts, and transactions run `BEGIN IMMEDIATE` so writers queue on `busy_timeout` instead of failing on lock upgrades.

### The recording state machine

States and the allowed transitions are defined in `citizens/services/recording_states.py`. The main path is
`CREATED, RECORDING, FINALIZING, (WAITING_FOR_CHUNKS), ASSEMBLING, AUDIO_READY, TRANSCRIBING, TRANSCRIBED, ANALYZING,
READY_FOR_REVIEW, REVIEWED`. Error states are recoverable by retrying the step that failed: `UPLOAD_INCOMPLETE`,
`AUDIO_INVALID`, `TRANSCRIPTION_FAILED`, `ANALYSIS_FAILED`. Attaching audio or a transcript moves a failed recording
forward (see [Recovery and import](../organizers/recovery-import.md)).

### What "synchronized" means

After assembly the server stores a fingerprint of the ordered original chunks: SHA-256 of UTF-8 lines
`sequence:size:sha256\n`. The phone compares that fingerprint, byte count and chunk count against its own complete local
inventory, and requires validated, available server audio. Only then does it mark the recording verified and eligible for
normal local cleanup. A salvaged prefix, a gap, an unavailable file or an old unverified completion flag is insufficient.

## Recovery behaviour

* Network errors, rate limits and server failures back off and retry. Microphone capture continues locally while an
  upload is unavailable or rejected.
* A permanent rejection stops automatic upload retries and asks for attention; it does not silently stop an active
  microphone.
* Expired or revoked sessions do not hide local audio. The recovery screen offers a download, keeping the copy, or
  explicitly confirming its deletion. A fresh QR for the same assembly and table resumes the original recording. A
  session's lifetime (16 hours) runs from the phone's last contact.
* A finished recording does not end the table's round: while the round is open the phone offers "Record the rest of round
  N", never automatically, and the server keeps the first recording as part 1. The analysis waits for both parts.
* A microphone lost mid-round is bridged, not finished: no chunk for thirty seconds while the page is on screen makes the
  engine ask for its buffer; silence closes the MediaRecorder session, keeps everything captured and asks for the
  microphone every five seconds. When it returns, the same recording continues, the new session's chunks carry the next
  segment number, and the server remuxes each segment on its own before joining them (`audio_chunks.segment_number`,
  migration 0023). Only after ten minutes of refusals is the recording finished. Nothing is judged while the page is
  hidden: Android slows timers and iOS freezes the page.
* Audio the server received from a phone that never came back is assembled by itself after thirty minutes of silence. A
  phone that returns after that keeps its local copy and is told the server would not take more.
* The recovery screen holds the screen wake lock like every other screen. The wake lock is asked for whenever a screen has a
  reason to stay awake and again when the browser lets go of it; every outcome is in the device log (`wake_lock_acquired`,
  `wake_lock_released`, `wake_lock_failed`, `wake_lock_unsupported`).
* On phones that can share files, "Download audio file" opens the system share sheet instead of an anchor download, because
  Safari on iPhone navigates to a blob URL, which would unload the recorder page and lose whatever it was uploading.
* Failed local writes retain their blobs in memory for retry or download while the page is alive. That memory is **not**
  crash-safe, so a storage warning needs immediate attention.
* Unfinished server parts have no automatic expiry; they are reclaimed after verified assembly or explicit audio deletion.

## Losing a phone mid-round

The server cannot distinguish a dead battery from dead Wi-Fi: both simply stop sending chunks. So there are two release
paths:

* **`POST /recordings/{id}/replace-device`** (Hand over table): a person looked at the phone and it is finished. The recording
  moves to `UPLOAD_INCOMPLETE` with `error_code=DEVICE_REPLACED`, stamped `superseded_at`, and, if any chunk arrived, is
  assembled and transcribed.
* **The automatic takeover** in `start_recording`: no chunk for `STALLED_DEVICE_SECONDS` (120) while still RECORDING. The
  original recording is left open so a phone that was merely offline can still upload everything.

`superseded_at` marks "this belonged to a device that has gone" independently of state; every guard asking "has this table
recorded this round?" ignores rows carrying it. Both halves are analysed as one table (`table_recordings()`), with a
methodology note that the device changed.

Since 0.7 a recorder with no chunk for 300 seconds (`AUTO_CLOSE_SILENT_SECONDS`) is finished by the server, and
**Finish recording** on the Live tab does the same after a 90-second grace (`FINISH_REQUEST_GRACE_SECONDS`). A recording closed
this way still accepts what the phone sends afterwards: the next chunk opens a new recording of the same table and slot
(`continued_from_id`), transcribed and folded back into the analysis.

## Several recorders per table, one live source

`recorder_sessions.slot` numbers a table's recorders: the table's own code is slot 1, an added recorder gets the next
number, and slots are never reused. The one-recording-per-table guard holds per slot. `services/table_recordings.py` is the
home of "every recording of this table"; the analysis merges recordings that overlap in time (as plenary always did) and
concatenates ones that follow each other.

Only one recording per table feeds live captions: `recordings.live_source` with a partial unique index
(`services/live_source.py`). The first recorder to start takes it, a backup's chunks are stored but never handed to the
caption engine, any recorder still in progress can be promoted from its phone or by the organizer, and every path that
stops a recording passes the source to a sibling still recording.

### Plenary merging

Several phones capture the same talk from different spots, so their transcripts overlap. `merge_plenary_segments`
(`citizens/services/analysis.py`) aligns every segment on the server clock (`recording.started_at + segment.start_seconds`),
coalesces within each device first, then drops near-duplicate utterances from different devices within a few-second window
(a stdlib `difflib` fuzzy match), keeping the longer copy and its segment ids so evidence citations stay valid. Speakers are
not unified across devices. Every device transcribes independently, so plenary costs N times the transcription.

## Table readiness

`services/readiness.py` turns heartbeat age, the heartbeat payload, each recorder's recording and the live source into READY,
NEEDS_ATTENTION or BLOCKED with structured reason codes (`NO_RECORDER`, `RECORDER_OFFLINE`, `MIC_UNAVAILABLE`,
`LOW_STORAGE`, `LOW_BATTERY`, `UPLOAD_STALLED`, `LIVE_STT_UNAVAILABLE`), each a blocker or a warning. It is in the monitor
payload and at `GET /rounds/{id}/readiness`.

## Clearing audio off the phones

Closing the assembly sets `device_audio_purge_requested_at`, automatically when `auto_purge_device_audio` is on (the default)
or on demand. The server cannot push, so the flag rides the status poll every recorder already makes. **Reopening withdraws
the automatic request** (`purge_requested_automatically`, migration 0021) but not one the organizer sent by hand. The guarantee
is one-directional: a phone deletes only audio the server has already confirmed. The Files tab reports coverage, never
completion.

## Capabilities: the first phone decides

A phone that already joined makes the QR code for the next phone, and the code carries its meaning: `ADD_RECORDER_TO_TABLE`
or `ADD_TABLE`. The scanner never chooses. They share the row, hashing, vault, rate limit and brute-force protection with the
printed table codes (`recorder_invites.purpose`, `services/capabilities.py`), live fifteen minutes and are single-use: the first
scan claims `consumed_at` with a conditional UPDATE under the writer lock, the second gets 410.

## Before using this build for an assembly

1. Back up the database and audio volume before upgrading, and deploy backend and rebuilt recorder assets together.
2. Check the actual proxy path permits the part, status and finalize routes and binary bodies of at least 1 MiB. Check storage
   supports file and directory fsync.
3. Rehearse over the venue's HTTPS connection on the actual Android and iPhone devices: capture, disconnect Wi-Fi, reconnect,
   finish, play the server export, then reload recovery and a fresh QR after session expiry.
4. Keep the recorder page open and the phone powered. Use an independent backup recorder for an irreplaceable assembly.
5. Before clearing devices, verify the server recording and preserve a backed-up export.

Automated tests use temporary storage and fake microphones. They do not certify physical power-loss durability, Safari
background behaviour, microphone quality or the production reverse-proxy configuration.
