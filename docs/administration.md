# Administration guide

Citizens is an **ExApp**: Nextcloud runs it as a container next to itself and
talks to it through the AppAPI proxy. This guide covers installing it, giving it
the API keys it needs, and understanding what leaves your server.

## 1. Requirements

* Nextcloud **32 or newer**
* The **AppAPI** app enabled, with a deploy daemon configured
  (Settings → Administration → External Apps → Deploy daemons)
* Docker available to that daemon, with enough disk for audio:
  roughly **10 MB per table per hour** of recording, plus the assembled copy

## 2. Install

Settings → Administration → **External Apps** → find *Citizens* → **Install**.
AppAPI pulls `ghcr.io/democracy-routes/citizens`, starts it, and enables it. The app
then appears in the top menu for every user.

Nothing else is required to start: without API keys the app records and stores
audio, but performs no transcription and no analysis.

## 3. Configure transcription and analysis

Open **Citizens → Settings** (visible to Nextcloud administrators only).

**Transcription.** Four engines are supported:

| Engine | Runs | Speaker labels | Live captions |
|---|---|---|---|
| Deepgram | hosted | yes | native streaming, with speakers |
| Mistral (Voxtral) | hosted | on final transcripts | Voxtral Realtime, no speakers while live |
| Whisper (OpenAI-compatible) | hosted **or your own server** | only on diarizing servers | rolling 20-second windows; a line may be revised |
| Vosk | **your own server**, offline | no | native streaming, no punctuation |

Any endpoint speaking the OpenAI audio API works for Whisper (OpenAI itself,
Speaches, whisper.cpp, LocalAI, vLLM, WhisperX). Deepgram's caption endpoint is
configurable too, so a self-hosted server speaking the same streaming protocol —
WhisperLiveKit, for example — can drive captions without leaving your network.

Paste the API key for hosted engines, or the endpoint URL for self-hosted ones,
and use the *Test* button before saving — it checks what you typed.

Choosing **Whisper against your own server** or **Vosk** means recordings are
never sent to a third party. A Whisper server that adds diarization (WhisperX-
based, or OpenAI's `gpt-4o-transcribe-diarize` model) keeps speaker labels;
plain Whisper and Vosk produce transcripts without them, and reports then omit
the "who said it" attribution while keeping every quote and finding.

### Live captions and the final transcript

Two checkboxes decide what is produced, and they work independently:

| Live | Final | What happens |
|---|---|---|
| ✓ | ✓ | Tables see captions while they talk; each recording is transcribed again afterwards from the complete audio. **The final transcript is the record** and the one the analysis reads. |
| ✗ | ✓ | No captions during the round. Each recording is transcribed once it is uploaded, and that is the record. |
| ✓ | ✗ | **The captions are the record.** Nothing is transcribed a second time. |
| ✗ | ✗ | Nothing is transcribed at all: audio is stored and there is no transcript, no analysis and an empty report. |

Live-only is worth choosing deliberately, not just a way to save a click.
Transcribing the finished audio a second time costs roughly ten minutes of
processing per half-hour table — for text a self-hosted engine already worked
out while listening. Skipping it matters most on a small server running Vosk
for ten tables at once.

What you give up is accuracy and completeness. Captions are produced under time
pressure: audio is dropped if the engine falls behind (logged when it happens),
and a session that fails resumes after a cooldown, so speech in that window is
never captioned. A report built from captions says so in its methodology note,
in every format, so a reader knows which kind of record they hold.

Nothing is stuck. The audio is kept, so **Re-transcribe** on any table's row in
the Files tab transcribes it properly from the stored audio and re-runs the
analysis — that works even with Final transcription switched off.

### Running Vosk yourself

Vosk needs **a separate model per language**, but one server can hold several:
each recording names the model it wants, and the language you set on an assembly
chooses it.

`scripts/vosk-up.sh` starts the server. It downloads nothing: fetch a model when
you know you need that language, which you can do the day before a session.

```
scripts/vosk-model.sh --list                       what is installed
scripts/vosk-model.sh vosk-model-small-de-0.15     add German
scripts/vosk-down.sh                               stop (--purge deletes models)
```

In Settings → Audio → Vosk, set the server URL and, for each language, the
**model name** — switching model is editing that name:

```
Server URL   ws://citizens-vosk:2700

             Live captions                  Final transcript
Italiano     vosk-model-small-it-0.22       vosk-model-small-it-0.22
English      vosk-model-small-en-us-0.15    vosk-model-small-en-us-0.15
```

A blank final model reuses the live one, and a language with no row uses
whatever model the server started with — so a half-filled table still
transcribes rather than failing. The two columns let a fast model produce
captions while a more accurate one produces the transcript; Vosk's large models
are 1.2–1.9 GB each, so that only pays off on a machine with the memory for it.

**Models load on first use and are freed when idle** (30 minutes by default,
`VOSK_MODEL_IDLE_SECONDS`), and only one is held at a time (`VOSK_MODEL_CACHE`).
An assembly uses one language, so an idle server costs a few MB rather than a
few hundred. A model in use is never unloaded, however long the round runs.

Two things worth knowing. The server must be reachable **from the app
container**, so use the container name rather than `localhost` — `localhost`
would point the app at itself. And Vosk has no authentication, so never publish
its port beyond `127.0.0.1`; the app reaches it over the shared Docker network.

The script runs a lightly patched `asr_server.py` (in `scripts/vosk/`): upstream
switches models process-wide and reloads from disk on every connection, which
would let two assemblies in different languages take each other's model, and it
never releases a model once loaded. The patch makes the choice per-connection,
caches loads, and frees idle models. A small model is about 230 MB resident.

**AI analysis.** Any OpenAI-compatible endpoint works: Mistral, OpenAI, or a
self-hosted server such as Ollama or vLLM. Set the base URL, model and key.
Choosing a self-hosted endpoint keeps transcripts on your own infrastructure.

**Organisation.** Your organisation name and logo appear on the PDF reports.

**Additional analysis instructions** apply to every assembly on the instance;
each assembly can add its own instructions on top (topic context, glossary).

API keys are stored in Nextcloud's app configuration marked *sensitive*. They
are never sent to browsers, never written to logs, and never reach the phones.

## 4. What leaves the server

| Step | What is sent | Where | When |
|---|---|---|---|
| Transcription | the assembled audio of one recording | Deepgram, Mistral, or the Whisper endpoint you configure (which can be your own server) | only after an admin configures an engine, and only with **Final transcription** enabled |
| Live captions | ~10-second audio chunks during recording | whichever engine is configured — none if it is self-hosted | only if live captions are enabled |
| Analysis | transcript text (never audio) | the configured endpoint — may be your own server | only after an admin configures it |

With live captions only, the assembled recording is never sent anywhere: the
chunks streamed during the round are the sole egress, and with Vosk or a
self-hosted Whisper server there is none at all.

Audio, transcripts, findings and reports live in the app's own persistent
storage, never in users' Nextcloud files. See [privacy.md](privacy.md) for the
full data-handling note, and give participants a privacy notice before you
record them.

## 5. Data management

Each assembly has a **Files** tab listing every table's audio with its size and
duration. From there an organizer can download one table's audio, download all
of it, export the **whole session** as a portable archive (metadata, audio,
transcripts and report), or delete audio and transcripts — per table or for the
session — without deleting the assembly. Deleting an assembly deletes its
stored files too.

**Re-transcribe** on a table's row transcribes it again from the stored audio,
replacing whatever transcript is there and re-running the analysis. A transcript
built from live captions is marked `live` in the same list, so it is clear which
tables are worth redoing. Quotes inside existing findings referred to the old
text, so they are marked as removed rather than left pointing at nothing.

**Automatic retention.** Settings → General sets how many days after an assembly
is **closed** its audio is deleted; `0` keeps it indefinitely, and an individual
assembly can override the instance default. Deletion runs from a periodic sweep
and is audit-logged. It removes **audio only** — transcripts, findings and
reports are the record of the assembly and are never touched by retention.
Deleting those is still manual, from the Files tab.

## 6. Backups

The app keeps everything in the persistent volume AppAPI mounts at `/data`:
SQLite database, audio, transcripts and logs. Back that volume up together with
Nextcloud itself. The database is safe to copy while running (WAL mode), but a
snapshot taken while a recording is uploading may miss its most recent chunks.

## 7. Troubleshooting

**The app is not in the top menu.** Check External Apps shows it enabled, then
look at the container logs — the app logs `missing_environment` if AppAPI did
not pass `APP_SECRET` or `NEXTCLOUD_URL`.

**Phones show only a spinner forever.** Their QR codes were generated by an
older version of the app. Regenerate the codes from the QR tab.

**A phone says it cannot reach the assembly.** The table is still joined and
anything recorded on it is safe — the phone keeps its session and retries. It
only asks for a new QR code when the server has actually rejected the session
(a revoked invite, a deleted assembly).

**A phone cannot start recording.** In live (orchestrated) mode a round must be
started by the facilitator first; a closed session refuses new recordings.

**Transcription never happens.** Check Settings for a configured key and use
*Test*; the recording's state in the Files tab shows where it stopped. If both
transcription checkboxes are unticked nothing is transcribed at all — Settings
warns about this.

**A table shows TRANSCRIPTION_FAILED with live captions only.** The caption
engine never connected, or heard nothing it was confident about, so there was
nothing to keep. The audio is unaffected: fix the engine and use
**Re-transcribe** on that table.

**A table is stuck in ASSEMBLING.** Almost always a full disk: the chunks are
safe and the job backs off rather than discarding them. The Files tab says so
and offers **Retry** on that recording — free some space, then use it. If the
recording is abandoned instead, the round's analysis proceeds without it.

**A table's phone died and they want to use another one.** Open the Live tab
and press **Replace device** on that table. The recording so far is finished
and transcribed — usually most of the round — and the table carries on by
scanning the same QR code on any phone. If nobody presses it, a replacement
phone is let in automatically after two minutes of silence; in that case the
first recording is left open, so a phone that was merely offline rather than
dead can still upload what it recorded while disconnected.

**Participants used their own phones.** Close the session, then use **Clear
audio from the table phones** on the Files tab. It reaches phones whose
recorder page is still open and reports how many confirmed — it is coverage,
not a guarantee. A phone only deletes audio the server has already confirmed,
so nothing can be lost.

**I approved more findings after closing, and the phones still show the old
report.** Closing freezes the version participants read, and reopening leaves
that frozen copy alone on purpose — so a phone's copy does not change under
someone mid-read. Press **Update the published version** on the Report tab to
push the current content. The same applies after renaming an assembly: the name
inside the frozen report changes only when you update it.

**The assembly name or language is wrong.** Both are on the Overview tab under
*Assembly details*. The language locks once any table has recorded, because it
decides how audio is transcribed and which model is used — changing it then
would leave one assembly with transcripts in two languages. Fix it before the
first round, or create the assembly again.

**A table shows "low battery".** Only Chromium reports this, so a table showing
nothing is unknown rather than fine. Swap the phone between rounds; a phone
that dies mid-round costs you the rest of it.

**A table shows "low storage".** The phone is running out of room. It reports
free space on every heartbeat, and this appears while there is still time to
act — finish the round, then swap the phone or clear its synchronized audio.

**Nothing on the Live tab updates.** Look at the timestamp above the table
grid. If it says "Reconnecting", the numbers on screen are from the time shown
and the server is unreachable; the view dims to make that unmistakable.

Health endpoint: `GET /api/v1/health` through the proxy reports the database,
storage, free disk and any missing configuration.
