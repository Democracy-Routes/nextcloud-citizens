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
  `scripts/dev-up.sh` on the day.
- [ ] **Prove the analysis provider, not just its key.** Settings → Test for
  the analysis endpoint now sends one real completion to the configured model
  and repeats the provider's reason if it refuses; "Connected" from the old
  models listing hid a workspace whose every chat call was refused with 403.
- [ ] **Charge the phones, and know which ones they are.** Every table phone
  should start the day above 80%, plugged in where the venue allows, and be a
  device you have already rehearsed with — not one somebody brought that
  morning.

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
  recovery screen and resume. That reload is the single most common real-world
  event; know what it looks like before a citizen sees it.
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

## What this deliberately does not cover

iOS Safari's background behaviour, a production reverse proxy you have not
tested the `/parts` routes through, and power-loss durability mid-round are
listed in [recording-reliability.md](recording-reliability.md)'s own
"automated tests do not certify" paragraph. If your venue depends on any of
them, rehearse it specifically — the dress round above is the place.
