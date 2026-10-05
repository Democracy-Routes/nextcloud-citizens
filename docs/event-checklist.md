<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->

# Running one assembly, rehearsed

A day-of runbook for a single orchestrated assembly on hosted speech-to-text
(Deepgram or Mistral). It exists because an hour of rehearsal on the actual
phones is worth more than any test suite — the suites prove the code; this
proves the room. Read [recording-reliability.md](recording-reliability.md)
first for what the software can and cannot survive.

**The honest headline, before anything else:** audio is the primary record,
and no software guarantees capture through a dead battery, a killed browser,
a lost microphone, or erased browser storage. Everything below is arranged so
that any of those happening is an annoyance, not a lost table — and so the
software's own failure modes are ones you have already watched happen in a
dress round, not ones you meet for the first time with fifty citizens in the
room.

## This week, before the day

- [ ] **Settings is configured and *proven*.** Citizens → Settings: the STT
  key (or endpoint) and the analysis endpoint are set. Then prove it end to
  end on the production instance: create a throwaway assembly, record thirty
  seconds on one phone over the venue's HTTPS path (not localhost), let it
  transcribe and analyse, confirm a report appears, delete the assembly. If
  the report never appears, nothing later in this document matters — fix the
  keys/endpoint now, not on the day.
- [ ] **Decide `auto_purge_device_audio` now.** It decides whether closing
  the assembly asks every phone to delete its local copy. For citizens' own
  phones, leave it on (the default). For organization phones you intend to
  inspect first, turn it off. Either is correct, and changing it later is
  safe — reopening withdraws only the request the close itself made, whatever
  the toggle says by then — but decide it before the day so nobody has to
  reason about it in the room.
- [ ] **Print the consent forms.** [consent-form.md](consent-form.md) is a
  bilingual information notice and consent form written from what the
  software actually does; fill in the bracketed fields (controller, contact,
  hosting, the retention you set) and collect one per participant before the
  first round. The phone's information screen stays as the second step.
- [ ] **Take a snapshot, and rehearse the restore.** `scripts/backup-citizens-data.sh`
  (see [administration.md](administration.md) § Backups) — then restore it into
  a throwaway volume and count the assemblies. A backup nobody has restored is
  a hope.
- [ ] **Check disk headroom.** `scripts/event-status.sh` prints free space on
  the data volume; a 40-minute round of ten tables is roughly 400 MB, and
  unfinished parts are not auto-expired. Leave comfortable headroom, not
  "enough."
- [ ] **Freeze the server.** A development container runs the checkout with
  auto-reload: any file saved on the host restarts the server mid-round and
  kills every live-caption session. The day before: stop every editor and
  agent on the host, run `sh scripts/event-up.sh` from the commit you tested
  (immutable image, no bind mount, no reload, 2 GiB, INFO logs), confirm
  `occ app_api:app:list` still shows the app enabled, then
  `python3 tests/load/load_h_realtime_assembly.py --smoke`. After this, nobody
  opens the repository until the event is over. Never run `make up` or
  `scripts/dev-up.sh` on the day. On an instance where AppAPI installed the
  app from the image (docs/administration.md § 2) there is nothing to freeze:
  the container already runs the tagged image with no bind mount — give it
  `docker update --memory 2g --memory-swap 2g nc_app_citizens` and run the
  same smoke test.
- [ ] **Prove the analysis provider, not just its key.** Settings → Test for
  the analysis endpoint now sends one real completion to the configured model
  and repeats the provider's reason if it refuses; "Connected" from the old
  models listing hid a workspace whose every chat call was refused with 403.
- [ ] **Charge the phones, and know which ones they are.** Every table phone
  should start the day above 80%, plugged in where the venue allows, and be a
  device you have already rehearsed with — not one somebody brought that
  morning.
- [ ] **Set every table phone so its screen cannot go off on its own.** The
  page asks the browser to keep the screen awake, but a browser can refuse
  and a phone can override it, and a dark screen is a phone that may stop
  recording (iPhones do). iPhone: Settings → Display & Brightness → Auto-Lock
  → Never, and Low Power Mode off. Android: Settings → Display → Screen
  timeout → 30 minutes (the longest offered), Battery saver off; on a Samsung
  also Settings → Battery → Background usage limits → make sure the browser
  is not among "Sleeping apps". The Live tab shows "screen may lock" on a
  phone whose browser did not grant the lock; that is the phone to do this on
  first. Undo it after the event.
- [ ] **Scan the QR codes on the day, not the evening before.** A session
  lives 16 hours from the phone's last contact; a phone that scanned and was
  then switched off overnight can still arrive at the first round expired,
  and re-scans on the armed screen. Harmless, but do not build the morning
  around it.
- [ ] **Run the device rehearsal below once on the real phones**, on the
  venue's Wi-Fi, before the dress round. It takes about ninety minutes and is
  the only test that covers the browsers the event actually uses.

## Morning of — the dress round (do all of this)

Run a real ~2-minute round with the actual table phones, on venue WiFi, with
the facilitator at the Live tab. The point is not that it works; it is that
you *watch* the failure modes recover:

- [ ] All tables join from their QR, pass the consent screen, and show
  recording.
- [ ] **Kill WiFi on one phone for 30 seconds, mid-recording.** It should
  keep recording (the chunk counter keeps climbing) and catch up cleanly when
  WiFi returns. You have now seen the offline-first design work; a venue
  dropout later in the day will not be a surprise.
- [ ] **Reload a second phone's page, mid-recording.** It should land on the
  recovery screen, upload what it captured, and then — because the round is
  still open — offer "Record the rest of round N". Tap it; the table now has
  two recordings that the Files tab lists as part 1 and the rest. That reload
  is the single most common real-world event; know what it looks like before
  a citizen sees it.
- [ ] End the round. Confirm every table reaches `AUDIO_READY` on the Live
  tab — not "synced" on the phone, the green state on the server.
- [ ] **Download the export for one table and actually play the audio.** A
  download starting is not proof a file saved or is playable.
- [ ] Delete the dress assembly.

## During the assembly

- [ ] `sh scripts/event-status.sh` every half hour, on a second screen: the
  job runner has no page of its own, and this is the only view of what is
  queued, retrying (and why), or failed — plus memory, disk and whether the
  frozen container is still the one running.
- [ ] When a table shows a failure, **read the note under the pill** on the
  Files, Live or Analysis tab before pressing anything. "Retrying
  automatically — next in 90 s" means wait; "rejected the API key" means
  Settings; a cancelled or failed run means Re-run. The Analysis tab's
  "Cancel pending analysis" stops jobs that are queued or waiting for a retry;
  one already mid-request finishes within five minutes.
- [ ] The facilitator keeps the **Live tab open the entire time.** Battery
  levels report there per table; a phone heading below ~20% is a handover
  *now* (Live tab → replace device with any other phone's QR), not a dead
  table in twenty minutes.
- [ ] One **independent backup recorder** (a real audio recorder, or a phone
  running its own voice-memo app, that is *not* part of Citizens) runs at the
  facilitator's table for the whole event. A second tab on a table phone is
  not independent. If a table's Citizens recording dies entirely, the
  discussion still exists — this is the closest thing to a guarantee that
  exists.
- [ ] If a phone dies anyway: hand the table to any other phone from the Live
  tab, or let the automatic takeover do it after two minutes of silence. The
  half already recorded is transcribed and analysed with the rest; the round
  reads as one discussion. You rehearsed this in the dress round.
- [ ] A table that matters can have a **second recorder phone** from the
  start: on the table's phone tap *Add Recorder to this Table* and scan the
  code with the second phone (it joins as Recorder B). Both record; only one
  feeds the live captions; if either dies the other carries on. A table that
  turns up unplanned is added from any joined phone with *Add new Table*, or
  from the QR tab's *Add a table* — it gets the next number, a colour and its
  own printed code.

## After — in this order

1. [ ] Close the assembly. Wait for processing; read the analysis and approve
   or reject findings — this is the human-review step, not a formality.
   Review the cross-table findings only once the last table is in: they are
   regenerated every time a table finishes. Do not press "Re-run analysis"
   afterwards unless a transcript changed — it replaces every finding of the
   round, reviews included.
2. [ ] **Export the reports and the audio, download them, and open one.** Only
   after you are holding a copy you have *opened* do you touch the next step.
3. [ ] **Only now** "Clear audio from the table phones" — and only if that was
   the plan for these devices. The request tells each phone to delete only
   what the server confirmed it holds, so it cannot destroy a last copy — but
   it is still worth reading the coverage line ("N of M table phones reported")
   and treating it as a report, not a promise; a phone already carried out of
   the building will simply not have answered.

## The device rehearsal (once, on the real phones, ~90 minutes)

Automated tests run on Firefox with a fake microphone; the event runs on
iPhones and Androids over venue Wi-Fi. Nothing but this covers the difference.
Set up a throwaway assembly ("Prova", orchestrated, three tables, rounds of
three minutes), keep the Live tab and the Files tab open on a laptop with
`sh scripts/event-status.sh` in a terminal, and scan fresh QR codes on three
phones: an iPhone (Safari), an Android (Chrome), and a third of whichever kind
you have most of. Timers to keep in mind: STALE after 45 s, Hand over table
offered after 120 s, the upload timeout after 20 min, automatic assembly of
stranded audio 30 min after that.

0. [ ] **Microphone permission by way of arrival.** On each phone open the
   same QR from the camera app, from a link pasted in WhatsApp, from a QR
   reader app, and from the browser with the microphone denied for the site.
   Note which of these fail the microphone check and with what text. The
   rehearsals logged 53 refusals; a browser embedded in another app never
   gets the microphone, and the fix there is "open this in Safari/Chrome",
   which the screen does not yet say.
1. [ ] **Happy path.** Three phones, one round. Pass: all three RECORDING on
   the Live tab within a minute of each other; at End round every table
   reaches AUDIO_READY then TRANSCRIBING within two minutes; the Files tab
   shows durations near 3:00; every phone says "synchronized", not "uploaded";
   no FAILED job on the status screen.
2. [ ] **Wi-Fi gone for 90 s on the iPhone, mid-round** (airplane mode).
   Pass: STALE then CONNECTED, the pending count rises then drains, Replace
   device appears and is **not** pressed; at End round the duration is the
   whole round; the device log shows `chunk_upload_failed`, `network_online`,
   `chunk_acked`.
3. [ ] **Screen off 60 s, then another app for 60 s — on the Android AND on
   the iPhone**, same round. First, the screen should not go off by itself
   at all: leave a phone untouched for three minutes while it records and
   check it is still lit (the device log has `wake_lock_acquired` at the
   start of the round; `wake_lock_failed` or `wake_lock_unsupported` means
   that model needs auto-lock set to Never by hand, and the Live tab shows
   "screen may lock"). Then press the power button. Pass, one of two ways:
   chunks keep coming while hidden (`capture_after_background` with
   `chunksWhileHidden` > 0, no gap over 15 s — Android usually), or the
   phone shows "interrupted" on return and then "Recording resumed — N s not
   captured" (`capture_interrupted` then `capture_resumed`; iPhone usually),
   and at the end of the round the Files tab has **one** file for the table
   whose duration is the round minus the gap. Fail: a gap with no
   `capture_resumed`, "capture interrupted" that never clears on the Live
   tab, or two files. `python3 scripts/device-report.py --since 1` prints all
   of this per phone.
4. [ ] **Reload mid-round on the iPhone**, let the recovery screen sync.
   Pass: "Record the rest of round N" appears; tap it; the Live tab shows the
   first part under the new recording; after the round the Files tab lists
   two files for the table. Then on the Android: reload, tap "Skip for now",
   "Ready"; the same button must appear on the armed screen.
5. [ ] **A phone that dies and nobody replaces.** Force-close the browser on
   the third phone at 1:00 and leave it. Pass now: STALE at 45 s, Replace
   device offered at 120 s (leave it); End round; the status screen lists the
   RECORDING row. Pass after 20 min: UPLOAD_INCOMPLETE / UPLOAD_TIMED_OUT,
   listed under "needs a decision" on the status screen, Retry offered on
   the Live and Files tabs. Pass after 50 min: assembled and transcribed by
   itself. (Press Retry if you cannot wait; that is what it is for.)
6. [ ] **Hand over table.** Kill Chrome on the Android at 1:00; when STALE
   has lasted two minutes, press Hand over table. Pass: the toast says the
   recording so far is being transcribed; the old row shows ASSEMBLING then
   AUDIO_READY under "earlier part — the phone was handed over"; reopen Chrome (or scan the same QR
   with the iPhone) and a new RECORDING starts; after the round the Files tab
   has two files for the table.
7. [ ] **A long backlog with nobody touching the phone.** iPhone in airplane
   mode for a whole round, Finish, reload to the recovery screen, Wi-Fi back
   on, then leave the phone alone for two minutes. Pass: it reaches
   "synchronized" untouched and the Files tab shows AUDIO_READY.
8. [ ] **Session revoked mid-round.** Regenerate the invites at 1:00 on the
   third phone's table. Pass: the phone shows the upload-blocked notice and
   keeps recording; the Live tab goes STALE; Finish leaves it on the failed
   screen; scanning a new QR opens the recovery screen and the backlog lands
   in the same recording → AUDIO_READY. Do not press Hand over table during
   this one.
9. [ ] **An iPhone older than iOS 18.4, if there is one.** One two-minute
   round, then play the `.m4a` from the Files tab. Otherwise the integration
   test covers the container.
10. [ ] **"Download audio file" on the iPhone.** Airplane mode, Finish, tap
    it: the share sheet must open, "Save to Files" must give a file that
    plays, and the page must still be there and finish uploading when the
    network returns.

Delete the "Prova" assembly when done.

## What this deliberately does not cover

iOS Safari's background behaviour, a production reverse proxy you have not
tested the `/parts` routes through, and power-loss durability mid-round are
listed in [recording-reliability.md](recording-reliability.md)'s own
"automated tests do not certify" paragraph. If your venue depends on any of
them, rehearse it specifically — the dress round above is the place.
