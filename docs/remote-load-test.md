# A ten-table rehearsal on your Nextcloud, run from outside

This page is for the operators of a Nextcloud that has Citizens installed and
is about to be used for an assembly. It describes a load test somebody else
runs against your instance, from the printed QR codes, with no access to your
server: ten virtual phones join ten tables and upload real recorded speech at
the pace real phones do, for as long as you agree to.

It exists because the things that break at ten tables are yours, not ours:
your reverse proxy, your PHP workers, your speech-to-text account, your disk.
Nothing we test on our own instance can tell you how yours behaves.

## What it does to your instance

Ten tables, each uploading a chunk of audio every ten seconds, plus a
heartbeat every twenty seconds, a status poll every eight, a caption poll every
twenty, and a diagnostic log every fifteen. That is roughly **75 requests a
minute per table**, all through the public recorder routes, all from one
address.

For a run of *N* minutes on ten tables:

| | |
|---|---|
| audio uploaded | about 3.5 MB per table-minute, so 10 × 8 min ≈ 280 MB |
| your speech-to-text bill | 10 × *N* minutes, **billed twice** — live captions while recording, then the final transcription |
| your analysis bill | one call per table plus one for the round, carrying whole transcripts |
| disk | the audio stays until somebody deletes the assembly |
| container memory | measured peak 368 MiB recording, 465 MiB transcribing, at ten tables. **2 GB is comfortable; 512 MB is not enough.** |

The audio is our own test recordings — real Italian speech, our voices, not
anybody's assembly — which your speech-to-text provider will process. If that
matters to you, say so and we will send a tone instead; it exercises everything
except the transcript.

## Before: four things, and the version is the important one

1. **Be on Citizens 0.6.2 or newer.** Up to 0.6.1 the status poll every phone
   runs held a database connection while it asked Nextcloud for six settings
   over OCS — through the same PHP workers that serve the phones. With five
   phones that exhausted a fifteen-connection pool and answered the phones with
   HTTP 500 for three minutes. Ten tables will do it faster. Check what you are
   running without logging in:

   ```bash
   curl -s https://YOUR-HOST/index.php/apps/app_api/proxy/citizens/recorder.html \
     | grep -o 'citizens-recorder.js?v=[0-9.]*'
   ```

   To update:

   ```bash
   occ app_api:app:unregister citizens
   occ app_api:app:register citizens <your-daemon> --wait-finish \
       --info-xml https://raw.githubusercontent.com/Democracy-Routes/nextcloud-citizens/v0.6.2/appinfo/info.xml \
       --env CITIZENS_PUBLIC_URL=https://YOUR-HOST
   docker update --memory 2g --memory-swap 2g nc_app_citizens
   ```

   Settings and data survive it. If you would rather see the problem before
   fixing it, that is a legitimate choice — say so, and the run is made
   deliberately against the old build, with the abort threshold tightened so it
   stops within a minute of the first failure.

2. **Create a throwaway assembly.** Orchestrated, ten tables (a few spares do
   no harm), one round whose length covers the run, and a name with "test" in
   it — the script refuses an assembly that does not look like a test, so that
   a wrong set of links can never inject our audio into a real one. Generate
   the invites and send us **the QR sheet PDF**: it prints each address as text
   under the code, so nothing has to be transcribed.

3. **Check the room.** A couple of gigabytes free on the data volume
   (`sh scripts/event-status.sh` prints it), and the container at 2 GB.

4. **Know where the traffic comes from.** We will tell you our address. Please
   note it somewhere: the public recorder route reports every 401, 403 and 429
   to Nextcloud's brute-force protection, so if a link has expired you may see
   our address throttled. `occ security:bruteforce:attempts <address>` shows it
   and `occ security:bruteforce:reset <address>` clears it.

## During: you press one button

The script joins the tables, prepares the audio, and then waits — printing a
banner — until the round goes ACTIVE. **Press "Start round" when we ask**;
there is no countdown to coordinate, and it waits up to half an hour. A script
cannot press it: the AppAPI proxy authenticates every non-public route with a
Nextcloud session cookie.

Then, if you can, watch:

- the **Live tab**: ten tables CONNECTED and recording. Two of them will show
  the red "capture interrupted" pill about 40% of the way in and clear it
  around a minute later — that is the test of the screen-off recovery, on
  purpose.
- `docker stats nc_app_citizens` and `docker logs -f nc_app_citizens`.
- your web server's error log.

**Press "End round"** when we say we are done. Uploads already in flight finish
regardless; ending the round does not cut them off.

## After: five commands, then delete the assembly

While it is fresh:

```bash
docker logs nc_app_citizens --since 60m 2>&1 \
  | grep -E 'QueuePool|database is locked|db_pool_wait|sweep_failed|stt_capacity|chunk_segment_started|audio_segments_joined'
grep -c AH00161 /var/log/apache2/error.log        # PHP workers exhausted (Apache)
sh scripts/event-status.sh | grep -E 'db pool|oom_killed|volume disk'
python3 scripts/device-report.py --assembly '<your test assembly>'
occ security:bruteforce:attempts <our address>
```

What good looks like: no `QueuePool` and no `database is locked`; `db pool`
with `slow_waits=0`; `AH00161` absent; two `chunk_segment_started` lines and
two `audio_segments_joined … method=copy` (the interrupted tables);
`device-report.py` showing a 45-second gap on exactly those two tables and
nothing unexplained elsewhere; and in the Files tab ten audio files of about
the round's length, two of them shorter by the length of the gap.

Then **delete the test assembly**. That removes the audio, the transcripts and
the findings; leaving it means keeping our voices and your provider's output on
your disk for nothing.

## What this does not tell you

It is ten machines on one connection, not ten phones on venue Wi-Fi: it says
nothing about microphones, about browsers, or about a screen that really goes
off. Those are in [event-checklist.md](event-checklist.md)'s device rehearsal,
which somebody has to do on the actual phones. This test covers the half of the
system that lives on your server.
