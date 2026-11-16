# Before the day

This page lists what to prepare in the week before an assembly, what to print, and how to
rehearse on the phones you will use. The test suites prove the code; only a rehearsal in the
room proves the room.

!!! warning "No software guarantees capture"
    Audio is the primary record. A dead battery, a killed browser, a lost microphone or
    erased browser storage can still lose audio. Run one independent backup recorder (a
    real audio recorder, or a phone running its own voice-memo app that is not part of
    Citizens) at the facilitator's table for the whole event. A second tab on a table phone
    is not independent.

## This week

* Configure and prove Settings. In Citizens, Settings, set the speech-to-text key (or
  endpoint) and the analysis endpoint. Then prove it end to end on the production
  instance: create a throwaway assembly, record thirty seconds on one phone over the venue's
  HTTPS path (not localhost), let it transcribe and analyze, confirm a report appears, delete
  the assembly. *Test* for the analysis endpoint sends one real completion to the configured
  model and repeats the provider's reason if it refuses.
* Decide `auto_purge_device_audio`. It decides whether closing the assembly asks every
  phone to delete its local copy. For citizens' own phones, leave it on (the default). For
  organization phones you intend to inspect first, turn it off. Either is correct, but decide before the day.
* Print the consent forms (below), or decide to rely on the phone's registration alone.
* Keep one table that is not recorded, and tell every facilitator why. a refusal blocks a
  table from recording until the refusing person is marked **Moved to another table** there
  (or changes their mind). One refusal is not outvoted by the rest. The Live tab shows this
  blocker as `PARTICIPANT_REFUSED`.
* Take a snapshot and rehearse the restore. See [Backups and restore](../admin/backups.md).
  
* Check disk headroom. `scripts/event-status.sh` prints free space on the data volume; a
  40-minute round of ten tables is roughly 400 MB, and unfinished parts are not auto-expired.
* Freeze the server (hand-run installs). A development container runs the checkout with
  auto-reload: a file saved on the host restarts the server mid-round and kills every
  live-caption session. The day before, stop every editor and agent on the host and run
  `sh scripts/event-up.sh` from the commit you tested. See
  [Updates and releases](../admin/updates.md). On an AppAPI-installed instance there is nothing
  to freeze: give the container memory with
  `docker update --memory 2g --memory-swap 2g nc_app_citizens`.
* Charge the phones above 80%, plugged in where the venue allows, and use phones you have
  already rehearsed with.
* Stop the screens going off. The page asks the browser to keep the screen awake, but a
  browser can refuse and a phone can override it. iPhone: Settings, Display & Brightness,
  Auto-Lock, Never, and Low Power Mode off. Android: Settings, Display, Screen timeout, 30
  minutes, Battery saver off; on a Samsung also Settings, Battery, Background usage limits, make
  sure the browser is not among "Sleeping apps". The Live tab shows "screen may lock" for a
  phone whose browser did not grant the lock. Undo this after the event.
* Scan the QR codes on the day, not the evening before. A phone session lives 16 hours from
  the phone's last contact.

## The participant notice and consent form

`docs/consent-form.md` is a print-ready information notice and consent form in English and
Italian, written from what the software actually does. Fill in the bracketed fields and collect
one form per participant before the first round. It is a template, not legal advice: have
counsel read it if you are a public body.

Fields you fill in:

| Field | Meaning |
|---|---|
| Controller | Organization name, postal address and email of the data controller |
| Data protection contact | Name and email |
| Hosting | Hosting provider and country |
| Recipients | The transcription and analysis providers actually selected |
| Retention | Audio retention as set on the assembly, or the zero-retention sentence |
| Record duration | How long the transcript, summaries, report and participant list are kept |

The same organization data is entered once in Settings, Organisation, and the phone's own notice
prints it: controller, address, contact, data-protection contact, hosting, supervisory
authority. Blank fields are left out, never shown as placeholders. Details are in
[Consent and the notice](../privacy/consent.md).

* The first box (audio recording, transcription and AI-assisted analysis) is required; the
  second (short anonymous quotations in the report) is optional and ticked by default.
* If anyone does not tick the first box, seat them at a table that is not recorded.
* Announce the recording aloud at the start and post a sign at the door; the software cannot
  know who was in the room.
* Confirm the "not used for training" sentence against your provider's terms before printing,
  or delete it.
* The legal basis offered is explicit consent (GDPR Art. 6(1)(a) and Art. 9(2)(a)). A public
  body may have another basis in law; counsel decides.

## The phone rehearsal

Automated tests run on Firefox with a fake microphone; the event runs on iPhones and Androids
over venue Wi-Fi. Set up a throwaway assembly (orchestrated, three tables, rounds of three
minutes), keep the Live tab and the Files tab open on a laptop with `sh scripts/event-status.sh`
in a terminal, and scan fresh codes on three phones: an iPhone (Safari), an Android (Chrome),
and one more. It takes about ninety minutes. Timers to keep in mind: STALE after 45 s, Hand over
table offered after 120 s, the upload timeout after 20 minutes, automatic assembly of stranded
audio 30 minutes after that.

Run these scenarios, numbered from 0. Each ends with what a pass looks like.

0. Open the same QR from the camera app, a link pasted in a chat app, a QR reader app, and the browser with the microphone denied. Pass: note which fail the microphone check and with what text. A browser embedded in another app never gets the microphone.
1. Happy path: three phones, one round. Pass: all RECORDING within a minute; every table reaches AUDIO_READY then TRANSCRIBING within two minutes; durations near 3:00; phones say "synchronized"; no FAILED job.
2. Airplane mode for 90 s on the iPhone mid-round. Pass: STALE then CONNECTED; pending count rises then drains; Replace device appears and is not pressed; full duration at the end.
3. Screen off 60 s, then another app for 60 s, on Android and iPhone. Pass: either chunks keep arriving while hidden, or "interrupted" then "Recording resumed". One file per table at the end.
4. Reload mid-round. Pass: recovery screen, then "Record the rest of round N"; two files for the table after the round.
5. A phone that dies and nobody replaces. Pass: STALE at 45 s; Retry offered after 20 min; assembled by itself later.
6. Hand over table. Pass: old row shows AUDIO_READY under "earlier part"; a new RECORDING starts on the replacement; two files.
7. Long backlog with nobody touching the phone. Pass: reaches "synchronized" untouched.
8. Session revoked mid-round. Pass: phone shows the upload-blocked notice and keeps recording; a new QR opens the recovery screen and the backlog lands in the same recording.
9. An iPhone older than iOS 18.4, if there is one. Pass: the `.m4a` from the Files tab plays.
10. "Download audio file" on the iPhone. Pass: share sheet opens, "Save to Files" gives a file that plays, the page survives.

The phone's own device log (`GET /api/v1/assemblies/{id}/device-report`, or
`python3 scripts/device-report.py --since 1` on the host) prints browser, wake-lock outcome,
hidden windows, gaps over fifteen seconds, interruptions and resumptions per phone.

## The morning of: the dress round

Run a real two-minute round with the actual table phones, on venue Wi-Fi, with the facilitator at
the Live tab. The point is not that it works; it is that you watch the failure modes recover.

1. All tables join from their QR, pass the consent screen, and show recording.
2. Kill Wi-Fi on one phone for 30 seconds mid-recording. It keeps recording (the chunk counter
   keeps climbing) and catches up when Wi-Fi returns.
3. Reload a second phone's page mid-recording. It lands on the recovery screen, uploads what
   it captured and, because the round is open, offers "Record the rest of round N".
4. End the round. Confirm every table reaches `AUDIO_READY` on the Live tab.
5. Download the export for one table and play the audio. A download starting is not proof
   a file saved or is playable.
6. Delete the dress assembly.

## What the rehearsal does not cover

iOS Safari's background behavior, a production reverse proxy you have not tested the `/parts`
routes through, and power-loss durability mid-round are listed in
[Recording pipeline and reliability](../architecture/recording-pipeline.md). If your venue depends
on one of them, rehearse it specifically.
