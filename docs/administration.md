# Administration guide

Citizens is an **ExApp**: Nextcloud runs it as a container next to itself and
talks to it through the AppAPI proxy. This guide covers installing it, giving it
the API keys it needs, and understanding what leaves your server.

## 1. Requirements

* Nextcloud **32 or newer**
* The **AppAPI** app enabled, with a deploy daemon configured
  (Settings → Administration → External Apps → Deploy daemons). Both daemon
  kinds work: the classic *Docker Socket Proxy* and *HaRP* (the app ships
  the `frpc` client HaRP needs and switches to it by itself).
* Docker available to that daemon, with enough disk for audio:
  roughly **10 MB per table per hour** of recording, plus the assembled copy
* `overwrite.cli.url` set to the public address of your Nextcloud
  (`occ config:system:get overwrite.cli.url`). The QR codes the tables scan
  are built on it; see *Public address* below if it cannot be set.

## 2. Install

### From the App Store

Settings → Administration → **External Apps** → find *Citizens* → **Install**.
AppAPI pulls `ghcr.io/democracy-routes/citizens`, starts it, and enables it. The app
then appears in the top menu for every user.

### From the image, on the command line

The same image, without the store — for an instance that installs apps by
hand, or a version the store does not carry yet. `occ` runs inside your
Nextcloud container (`docker exec -u www-data <nextcloud> php occ …`).

1. A deploy daemon, if there is none yet (Settings → Administration → External
   Apps → Deploy daemons shows the ones you have). For example, a Docker
   Socket Proxy daemon on the same host:

   ```
   occ app_api:daemon:register docker_local "Docker (local)" docker-install \
       http nextcloud-appapi-dsp:2375 https://cloud.example.org --net nextcloud
   ```

   The last URL is the address **the app container will use to reach
   Nextcloud**; the app also reads `overwrite.cli.url` for the phones, so an
   internal address here is fine. `--net` is the Docker network the Nextcloud
   container is on. HaRP daemons take `--harp …` options; follow the AppAPI
   documentation for the daemon itself.

2. Register the app from its `info.xml` — a local path readable by the
   Nextcloud container, or the raw file from the tag you are installing:

   ```
   occ app_api:app:register citizens docker_local --wait-finish \
       --info-xml https://raw.githubusercontent.com/Democracy-Routes/nextcloud-citizens/v0.6.2/appinfo/info.xml
   ```

   AppAPI pulls `ghcr.io/democracy-routes/citizens:<version>` (the `<image-tag>`
   in that file), creates the container `nc_app_citizens` and the volume
   `nc_app_citizens_data`, starts it, waits for `/heartbeat`, and enables it.
   `--wait-finish` returns when the app is enabled or prints why it is not.

3. Give the container the memory a real assembly needs — AppAPI sets no limit
   unless the daemon has resource limits configured in the UI:

   ```
   docker update --memory 2g --memory-swap 2g nc_app_citizens
   ```

4. Check: `occ app_api:app:list` shows `citizens <version> [enabled]`,
   `docker inspect nc_app_citizens --format '{{.State.Health.Status}}'` says
   `healthy`, and the *Citizens* entry is in the top menu. The container log
   (`docker logs nc_app_citizens`) shows `app_started` and a
   `public_url_resolved` line with the address the QR codes will carry.

**Public address.** The phones open
`<public address>/index.php/apps/app_api/proxy/citizens/recorder.html`. The app
asks Nextcloud for `overwrite.cli.url` and uses that; when it is unset it falls
back to the daemon's Nextcloud URL, which may be an internal name. To pin it,
pass the address at registration:

```
occ app_api:app:register citizens docker_local --wait-finish --info-xml … \
    --env CITIZENS_PUBLIC_URL=https://cloud.example.org
```

The same option accepts `CITIZENS_JOB_WORKERS` (default 10; `1` runs
transcriptions and analyses one at a time) and `CITIZENS_LOG_LEVEL`.

**The secret.** AppAPI generates the app secret and keeps it in its own
database and in the container's environment (`docker inspect nc_app_citizens`);
nothing on disk needs it. `scripts/event-status.sh` and
`scripts/backup-citizens-data.sh` find the AppAPI-created volume by
themselves.

### Hand-run container (manual-install daemon)

How the development and the first event instance run: the container is built
and started by `scripts/event-up.sh` from a checkout, and registered with a
*manual-install* daemon whose host is the container's name — see
`scripts/register.sh` and `docs/development-environment.md`. The AppAPI
daemon then pulls nothing and manages nothing; you do, with those scripts.

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

### Several recorder phones at one table

Since 0.7 a table may have more than one recorder phone. On any joined phone,
**Add Recorder to this Table** shows a QR code; the phone that scans it joins
the same table as Recorder B and records beside Recorder A. Both recordings
are kept, transcribed and analysed as one table; if one phone dies the other
is unaffected, and a replacement for the dead one still rescans the table's
printed code as before. **Add new Table** on any joined phone shows a code
that creates the next table — numbered and coloured, in every session, with
its own printed code on the QR tab — and makes the scanning phone its first
recorder. These codes live fifteen minutes and work once; the printed table
codes are unchanged. The QR tab's **Add a table** does the same from the
organizer's screen.

Only one phone per table feeds the live captions (the first to start). A
backup phone's caption panel says whose captions the room is reading and can
take them over; the Live tab shows which recorder carries them and the
organizer can promote another (`POST /api/v1/recordings/{id}/promote-live-
source`). When the carrying phone stops — finished, replaced, silent — the
captions pass to a phone still recording. A plenary room, whose phones all
used to open their own caption session, now opens one.

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

The app keeps everything in its persistent volume: SQLite database, audio,
transcripts, live captions and logs. An AppAPI-managed install has it in the
volume `nc_app_citizens_data` (mounted at `/nc_app_citizens_data`); the
hand-run container uses `citizens_data` at `/data`. Back that volume up
together with Nextcloud itself. The scripts below pick whichever exists.

`scripts/backup-citizens-data.sh` takes a consistent snapshot while the app
runs: `VACUUM INTO` copies the database as one transaction (WAL mode makes
this safe), the rest of the volume is tarred, and both are checksummed into
`/root/backups/citizens-data-<timestamp>/`. Set `CITIZENS_BACKUP_REMOTE` to an
rsync target to copy it off the host — a snapshot on the same disk as the data
protects against mistakes, not against the disk. Install it nightly:

```
install -m 755 scripts/backup-citizens-data.sh /usr/local/sbin/citizens-backup
( crontab -l 2>/dev/null; echo '30 2 * * * /usr/local/sbin/citizens-backup >> /var/log/citizens-backup.log 2>&1' ) | crontab -
```

A snapshot taken while a recording is uploading may miss its most recent
chunks; the phone still holds them and re-sends on reconnect.

**Restore** (rehearse it once on a throwaway volume before you need it):

```
docker volume create citizens_restore
docker run --rm -v citizens_restore:/data -v /root/backups/citizens-data-<stamp>:/in:ro alpine sh -c \
  'tar xzf /in/citizens_data-files.tar.gz -C /data && cp /in/citizens.db /data/citizens.db && chown -R 10001:10001 /data'
sqlite3 "file:$(docker volume inspect citizens_restore --format '{{.Mountpoint}}')/citizens.db?mode=ro" \
  'select count(*) from assemblies; select count(*) from recordings; select version_num from alembic_version'
```

To restore for real, stop the container, repeat the same into the live volume
(`nc_app_citizens_data` or `citizens_data`, or point the container at the
restored volume), and start it: migrations run at startup, so a snapshot from
an older version upgrades itself. Ownership is repaired at start as well — the
entrypoint hands the volume to the service user (uid 10001) if a restore left
it owned by root.

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
and press **Hand over table** on that table. The recording so far is finished
and transcribed — usually most of the round — and the table carries on by
scanning the same QR code on any phone. If nobody presses it, a replacement
phone is let in automatically after two minutes of silence; in that case the
first recording is left open, so a phone that was merely offline rather than
dead can still upload what it recorded while disconnected.

**A table's phone died and nobody replaced it.** After twenty minutes of
silence the recording shows UPLOAD_INCOMPLETE with "upload timed out"; the
audio that reached the server is on disk. Thirty minutes later it is
assembled and transcribed by itself. To not wait, press **Retry** on that
table (Live tab, next to Hand over table, or Files tab): it assembles the
contiguous part that arrived. `scripts/event-status.sh` lists such
recordings under "needs a decision".

**A table's phone lost the microphone mid-round — the screen went off, a
call came in — and the round was still going.** Nothing to do. The phone
notices within about forty seconds of being back on screen, shows
"interrupted", asks for the microphone back every five seconds and, when it
returns, carries on in the **same** recording (one file, one transcript; the
screen says how many seconds were missed). The Live tab shows "capture
interrupted" while it lasts — if it stays, somebody should pick the phone up
and look at it. Only after ten minutes without a microphone does the phone
finish the recording with what it has, and then the next paragraph applies.
A phone that shows "screen may lock" on the Live tab cannot hold its screen
awake by itself: set its auto-lock to Never in the phone's settings.

**A table reloaded the page and the round was still going.** The phone
uploads what it captured, then shows "Record the rest of round N" — on the
armed screen after the recovery, and on the finished screen. Tapping it
starts a second recording for the same round; the first is kept as part 1
("first part" on the Live tab, `-part1` in the export) and the table's
analysis waits for both. This one is never automatic: a table that pressed
Finish on purpose simply does not tap it. Once you end the round the offer
disappears.

**Participants used their own phones.** Closing the session asks the phones to
clear their copy automatically — that is on by default, and switchable per
assembly under *Assembly details* on the Overview tab. Turn it off if you want
the phones to keep their copies until you have downloaded and checked the
export. You can also ask at any time with **Clear audio from the table phones**
on the Files tab. It reaches phones whose
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

**A round ran past its time.** The Live tab counts up once the planned time
has passed and offers to end the round after a minute, with **Extend 5 min** and
**Keep going** beside it. Rounds used to end only when somebody clicked, which
is why tables drifted apart. The phones still get their own fifteen-second
"Keep talking" grace, so nobody is cut off mid-sentence. This runs in the Live
tab, so with that tab closed nothing ends by itself.

**Tables are ending at different times.** The Elapsed column on the Live tab
shows how long each table has been recording, and highlights any table that
started more than a minute after the earliest one — usually a table that armed
late or whose phone was replaced.

**Reviewing findings one at a time is slow.** The Analysis tab has filters for
review status and finding type, and **Approve N draft(s)** approves everything
still waiting in the round. Rejected findings are left alone, and anything
approved can still be edited or rejected afterwards. There is deliberately no
way to skip review: the report states that a person approved its findings.

**I re-ran the analysis and my reviews are gone.** A run replaces the whole
generation of findings it supersedes, approved and edited ones included — the
alternative, keeping them next to the new set, printed every theme twice in
the report. The dialog says so before you confirm. Cross-table findings are
regenerated automatically every time another table finishes its analysis, so
review those after the last table has come in, not while tables are still
arriving. A re-run that comes back with no findings for a table that had some
is refused and the previous findings are kept; the table's failure note says so.

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
