# On the day

The organizer runs the day from the assembly's **Live** tab on a laptop. Keep it open the
entire time: the battery levels, readiness warnings and timers all report there.

## Starting and joining

Phones scan the table's QR code, pass the information screen and register for consent, then
(in live mode) tap READY and sit on an armed screen. The Live tab shows "N/M tables ready" and
warns, never blocks, when you start with tables missing. In live mode a round must be started
by you; a closed session refuses new recordings.

Phones that scan a **single-use** code a second time on the same phone return to their
existing session instead of "This code has already been used". A different phone scanning the
same spent code still gets that error.

## The Live tab

The Live tab polls the round monitor and shows, per table:

* device connectivity (heartbeat age), chunk upload progress, and "local recording safe" only
  when a recent heartbeat reports healthy storage;
* battery level and free storage where the browser reports them (only Chromium does; a
  blank is unknown rather than fine);
* a readiness state, READY, NEEDS_ATTENTION or BLOCKED, with reason codes such as
  `NO_RECORDER`, `RECORDER_OFFLINE`, `MIC_UNAVAILABLE`, `LOW_STORAGE`, `LOW_BATTERY`,
  `UPLOAD_STALLED`, `LIVE_STT_UNAVAILABLE` and `PARTICIPANT_REFUSED`. One healthy recorder with
  no backup is READY; the only recorder offline is BLOCKED;
* an **Elapsed** column, highlighting any table that started more than a minute after the
  earliest one;
* a coverage percentage per recording (a recorder's badge turns red below 95%), "no audio has
  reached the server for N s" in red with an optional tone (the Sound button), and "in
  background", "capture interrupted" or "screen may lock" for a phone in those conditions;
* messages you can send to a table or its facilitator, and help requests (a raised hand) that
  stay against the table until you acknowledge them.

A timestamp above the table grid shows the last successful refresh. If it says "Reconnecting",
the numbers are from that time and the view dims. The Live tab polls; it does not use
WebSockets.

## Recorders

Each phone shows the recorder app: a hero table number, a pulsing record ring, a checklist and
caption bubbles. A table that matters can have a **second recorder phone** from the start:
on a joined phone tap **Add Recorder to this Table** and scan the code with the second phone
(it joins as Recorder B). Both record; only one feeds the live captions; if either dies the
other carries on. **Add new Table** on any joined phone, or **Add a table** on the QR tab,
creates the next numbered, coloured table with its own printed code. These added codes live
fifteen minutes and work once.

## Live captions

Live captions are shown on the recording phone while it records, from whichever engine is
configured. The recorder that started first carries them. A backup phone's caption panel says
whose captions the room is reading and can take them over; you can also promote another
recorder from the Live tab. When the carrying phone stops (finished, replaced, silent) the
captions pass to a phone still recording. Whether the captions also become the transcript
depends on the Live/Final switches; see [Settings reference](../admin/settings.md#live-captions-and-the-final-transcript).

## Replacing a phone

The server cannot tell a dead battery from dead Wi-Fi: both stop sending chunks. A dead phone
has stopped recording; a disconnected one is still recording locally and will upload later.

* **Hand over table** (Live tab): you looked at the phone and it is finished. The recording so
  far is finished and transcribed, and the table carries on by scanning the same QR code on any
  other phone. The half already recorded is analysed with the rest, and the report notes the
  device changed.
* **Automatic takeover:** if nobody does anything, a replacement phone is let in after two
  minutes of silence. The original recording is left open, because a timer only guesses.
* **Silent close:** a recorder that sends no chunk for five minutes is finished by the server
  with the audio already received (the Live tab says *Finished by the server after 5 minutes
  of silence*). You can also press **Finish recording** next to a recorder: it asks the phone
  first and finishes server-side after ninety seconds of no answer.
* **Late audio is kept.** If that phone keeps recording afterwards, the next chunk opens a new
  recording of the same table and slot (*Audio that arrived after the close, kept*), which is
  transcribed and folded back into the table's analysis, keeping approved findings.
* A phone heading below about 20% battery is a handover now, not a dead table in twenty
  minutes. Phones report their battery level while recording and prompt for a backup before
  they die.

A phone that loses the microphone mid-round (screen off, a call) notices within about forty
seconds, shows "interrupted", asks for the microphone again every five seconds and, when it
returns, continues in the **same** recording. After ten minutes without a microphone it
finishes with what it has.

## Ending a round

Past the planned time the Live tab counts up and, after a minute, offers to end the round,
with **Extend 5 min** and **Keep going** beside it. The phones still get their own 15-second
"Keep talking" grace. The ending is driven by the Live tab, so with that tab closed nothing
ends by itself. In independent mode tables finish themselves from the phone's clock. After you
end the round every table must reach `AUDIO_READY`; check that, not the phone's "synchronized".

**Record now** sessions have no planned time and no countdown; the table finishes when the
people at it press Finish.

## Watching the job queue

The job runner has no page of its own. Run `sh scripts/event-status.sh` every half hour on a
second screen: it shows what is queued, retrying (and why) or failed, plus memory, disk and
whether the frozen container is still the one running. When a table shows a failure, read the
note under the status pill on the Files, Live or Analysis tab before pressing anything:
"Retrying automatically - next in 90 s" means wait; "rejected the API key" means Settings; a
cancelled or failed run means Re-run. See [Troubleshooting](../admin/troubleshooting.md).

## The AI assistant

An optional AI assistant can offer one short sentence to a table's facilitator. It is off
unless an administrator or you turn it on, per assembly on the Overview tab; you can pause it
per table from the Live tab. See the [Settings reference](../admin/settings.md#ai-facilitator).
