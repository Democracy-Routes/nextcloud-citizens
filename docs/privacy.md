# Privacy & data handling

Citizens records people's voices, which is sensitive personal data. This
document describes **what the software actually does today**, so that an
organisation deploying it can write its own privacy notice and processing
record against something accurate.

Where a control does not exist yet, it says so. Nothing here is aspirational.

## What is stored, and where

Everything Citizens stores lives under the ExApp's own persistent storage
(`APP_PERSISTENT_STORAGE`, mounted at `/data`):

| Data | Location | Notes |
|---|---|---|
| Audio recordings | `assembled/` | one file per table per round |
| Upload chunks | `recordings/` | **deleted automatically** once the assembled file is verified; `manifest.json` keeps each chunk's checksum as the audit trail |
| Transcripts | `transcripts/` + database | segments and words, with speaker labels |
| Live captions | `live_captions/` | what a caption session heard, written when it ends; becomes the transcript when final transcription is off |
| Findings and reports | database | AI drafts plus human review decisions |
| Device diagnostics | `logs/devices/` | phone-side event log, capped at 5 MB per session |
| Application log | `logs/citizens.jsonl` | rotated, 10 MB × 5 |

Citizens never reads or writes Nextcloud user files.

In standalone mode (no Nextcloud), organizer accounts are stored in the app
database. An account holds a username, a display name and an email address,
and a password hash. Invitation and password-reset links are stored hashed and
expire. Deleting an account removes the account and its links.

## What leaves the server

**Nothing, until an administrator configures a provider.** A fresh install
performs no transcription and no analysis.

* **Speech to text.** Deepgram and Mistral are hosted services: with those, the
  assembled audio of each recording is sent to the provider once. **Whisper**
  works against any OpenAI-compatible endpoint, including one you run yourself,
  and **Vosk** runs entirely offline (its built-in engine runs inside the app container, so speech stays on the server) — with either, audio never leaves your
  infrastructure.
* **Analysis.** Only the *transcript text* is sent, never audio. Any
  OpenAI-compatible endpoint works, so this can also run on your own hardware.
* **Live captions** use the same engine as transcription and are shown on the
  recording phone while it records. When a session ends, what it heard is
  written to `live_captions/` — this is speech stored as text, and it is kept
  whether or not it is used. If **Final transcription** is switched off in
  Settings it becomes the assembly's transcript; otherwise it stays as a
  by-product that the transcription of the finished audio supersedes. It is
  deleted with the assembly, and with that recording's transcript.

The recorder tells each table which of these applies **before recording
starts** — see "Consent" below.

## Retention

* Raw audio retention is configurable in Settings as a number of days after an
  assembly is **closed**. `0` means keep indefinitely, which is the default.
  Individual assemblies can override the instance default.
* Deletion runs from a periodic sweep, is audit-logged (assembly, policy,
  number of recordings, bytes freed), and never logs content.
* **Zero retention (0.7): keep only the report.** A third choice, per
  assembly, beside the instance default and a day count. Once the assembly is
  **closed** and every transcription and analysis has actually finished, the
  audio, every transcript and the live-caption files are deleted outright,
  and a PDF of the frozen report is kept in their place — from then on the
  report-PDF download serves that file rather than rendering a new one.
  Nothing but the participant list and that PDF survives. **This cannot be
  undone**: the assembly can never be reopened afterwards, because there is
  no audio left to build anything from again. If the assembly was still being
  transcribed or analysed at closing time, zero retention runs as soon as
  that finishes, not necessarily the instant you close it.
* **Audio that arrives after a recording has been closed is not lost
  (0.7).** A recording the server finished on a phone's behalf — because the
  phone sent nothing for five minutes, or because an organizer pressed
  *Finish recording* on the Live tab and the phone never answered — still
  accepts whatever that phone sends afterwards: it opens a new recording of
  the same table and the same recorder, continuing the account, which is
  transcribed and folded back into the table's analysis (keeping any findings
  already approved). It is ordinary audio from there on, subject to
  retention — including zero retention — like any other recording.
* **Audio only.** Transcripts, findings and reports are the record of the
  assembly and are not touched by retention. Delete them explicitly from the
  Files tab of the assembly if you need to.
* Organisers can delete audio and transcripts at any time from the Files tab,
  and deleting an assembly deletes its audio, transcripts, live captions and
  exports with it. Deleting one table's transcript deletes that table's live
  captions too — the same speech in a second file.
* Deleting audio, whether by hand or by the retention sweep, also deletes that
  assembly's **export archives**. An audio bundle or session export contains a
  complete second copy of the recordings, and nothing but full assembly
  deletion used to reclaim one — so the sweep could report the audio purged
  while an entire copy of it remained on disk. Archives nobody collected are
  also swept after an hour.
* **Names people say out loud are in the transcript.** Speaker labels are
  anonymous — SPEAKER_01, never a name — but the transcript records what was
  said, so "Simone, you spoke too much" appears as spoken, and would reach the
  analysis service with everything else. Under *Assembly details* you can list
  names to be replaced with "Person A", "Person B" before the transcript is
  sent; any imported participant's name is included automatically. The
  transcript kept on this server is unchanged, so the report's quotes still
  show what was actually said.

  Two limits worth stating in your own privacy information. The list comes from
  the organizer, not from a detector — a name nobody listed is not replaced,
  and no attempt is made to guess, because a list of common first names would
  mangle ordinary words. And it protects the **analysis** step only: the audio
  sent for transcription carries the names as spoken, so if that matters, run a
  self-hosted engine (Vosk or a local Whisper) and nothing leaves at all.

* **The table phones hold a copy too.** Every recording is written to the
  phone's own storage before it is uploaded — that is what makes recording
  survive a bad network — so at the end of an assembly each phone still has its
  table's audio. When the phones belong to the organisation this is a matter of
  housekeeping. When participants use their own devices, **those devices are a
  processing location outside your control**, and you should say so in your
  own privacy information.

  Closing the session asks the phones to clear their copy automatically (on by
  default, switchable per assembly). The Files tab of a closed assembly also has
  **Clear audio from the table phones**,
  which asks each phone to delete its local copy. Two limits matter:

  * It reaches phones whose recorder page is still open, because the server
    cannot push to a phone — the request travels on a poll the recorder already
    makes. A phone that was closed and carried out of the building will act on
    it the next time the recorder is opened, while its session is still valid,
    and otherwise not at all. The screen reports how many phones have confirmed
    rather than claiming the job is done.
  * A phone only deletes recordings **the server has already confirmed it
    holds**. Audio still waiting to upload is kept, because that copy may be
    the only one. The phone says so, and that table should be shown to an
    organizer.

  Each phone also offers the same thing to its own user at the end of a round.
* **The device log is diagnostics, not a second recording.** Each phone ships
  an event log of its own session (`logs/devices/`, in the table above); the
  organizer's own report of it — `GET /api/v1/assemblies/{id}/device-report`,
  the same thing `scripts/device-report.py` prints from the host — contains
  event names and timestamps only: which browser, whether it held the
  screen's wake lock, how many audio chunks it captured while the page was
  hidden, where capture gapped. No audio and nothing spoken is in it, beyond
  the browser's own user agent string.
* **Sessions that never recorded, and spent single-use QR codes, are removed
  a week after they expired (0.7).** A phone, facilitator or participant
  session that expired without making a recording, and a single-use code
  already spent, are deleted seven days after they expired — including that
  phone's device log. A session that did make a recording is kept, because it
  is that recording's record of which phone made it.
* **Not implemented:** there is no automatic deletion of transcripts or
  findings, and no data-subject-request tooling. Both are manual today.

## Consent

Before a table can record, the recorder shows an information screen naming the
transcription engine, whether that engine is an outside service, how long audio
is kept, and that speakers are labelled only as "Speaker 1", "Speaker 2". The
table confirms before recording becomes available. The text is generated from
the server's live configuration, so it cannot drift from what the app does, and
it is shown in the assembly's own language rather than in English.

The screen offers a decline as well as a confirmation. A screen with only one
button is not a consent step, and a table with no way to say no previously had
to work that out by walking away from the phone.

Since 0.7 the screen is also where **individual consent is recorded**. The
notice is versioned — `2026-10.3` today — and rendered by the server from
the Settings (data controller and contact) and the live data-handling
facts, in the assembly's language, and hashed exactly as shown; the text
behind every hash is kept (`consent_notices`). It opens with a paragraph
making clear that recording is not a condition of taking part: a person who
does not consent can sit at a table that is not recorded. Each person
registers one at a time — on the table's phone, or on their own phone
through a registration code the table shows — giving a name (required), an
email (optional), and **two boxes**: a required one covering the audio
recording of the discussion at the table, its transcription and
AI-assisted analysis, and an optional one, ticked by default, covering
short anonymous quotations from the table in the assembly's report.
Leaving the required box unticked records a refusal; the optional box can
be unticked on its own without affecting the rest. The record
(`participant_consents`: who, where, method, notice version and hash, the
four flags the two boxes cover, the server's timestamp) is stored as given.
Registration is audited without name or email. The notice names the
transcription and analysis providers selected in Settings and prints the
organization data entered there (controller, address, contact,
data-protection contact, hosting, supervisory authority) — blank fields are
left out, never shown as placeholders.

Consent acts are append-only: nothing already recorded is overwritten, and
the newest act for a person is the one that counts everywhere it is
checked. From the table phone's own participants screen, or the
organizer's Participants tab, three actions each add a new act: **Changed
their mind** (offered only after a refusal) records a new act with both
boxes ticked again and the name unchanged; **Withdraws consent** records a
new act with every flag false — what was already recorded is kept and
keeps being processed, but the table cannot record this person again until
they are moved or change their mind; **Moved to another table** takes the
person off this table's roster for the sessions still to come, and leaves
their consent record untouched. The consent register (CSV or PDF, from the
Participants tab) lists every act ever recorded, one row per act, all under
the same participant's label.

If anyone seated at a table declined the quotations box, the report prints
no verbatim quotation from that table: the table's findings stand on the
analysis alone, the report states under that table that quotations from it
are withheld because a participant seated there did not consent to being
quoted, and cross-table findings borrow no quotation from that table
either. The methodology note explains why. This withholds by table, not by
the one person, because voices are not separated in the recording.

A **facilitator's own phone** (0.7) follows one table through a code the
table's phone shows. The server keeps only a hashed bearer with the table
number and timestamps (`facilitator_sessions`) — no name, no audio, no
captions: the facilitator's page reads the same roster (names only) and
messages the table's phones read, and what it writes (a prompt, a hand
raised) is audited under the session id. Registering for consent from that
phone goes through the ordinary registration code and record.

The **AI facilitator** (0.7, off unless an administrator or organizer turns
it on) sends a language model, once a minute at most, the last ~40 live
caption lines of a table with every known participant name replaced by a
pseudonym (the same `redact_names` list the analysis uses), the session's
question and time, and — only when the engine labels speakers — anonymous
speaking-time shares. It receives one sentence back, which is stored with
the table number, the model name and who it was delivered to
(`facilitator_interventions`), and shown on the facilitator's phone or the
table's phones. Thumbs up or down are stored as counts per intervention
(`facilitator_feedback`), never as who tapped. The model and endpoint are
the ones configured in Settings → AI facilitator, falling back to the
analysis model; the consent notice's analysis provider therefore covers it
when the two are the same service, and an administrator who points the
facilitator at a different provider should name it in the organization
data.

An assembly set to *Consent at the table: required* (the default for an
organized assembly) records a table only once at least one person seated
there has consented, **and only for as long as nobody seated there has
refused or withdrawn** — one refusal blocks the whole table; it is not
outvoted by the rest. The seat that counts is the seat of the current
session's seating plan — written by registration and by New seating —
falling back to the table the person registered at. The room procedure for
a blocked table is to mark the refusing person **Moved to another table**
(a table that is not recorded), on the table's phone or from the
organizer's Participants tab; the table can then record. The rule is
enforced where recording starts, not only on the phone. *Optional* (the
default for a spontaneous Session) shows the notice and offers registration
without blocking anything.

Every consent act is audited — `consent_changed` and `participant_moved`,
alongside the existing `participant_registered`. A table's own phone can
act only on people seated at its own table; the organizer can act on
anyone in the assembly. A closed assembly accepts no further consent acts.

The lawful basis documented in [consent-form.md](consent-form.md) is explicit
consent (GDPR Art. 6(1)(a) and Art. 9(2)(a)). Rights: erasing a participant
from the Participants tab erases their consent record (cascade); the export
carries every record and every notice text, so a subject-access request can
be answered from the archive; withdrawal is handled through the contact on
the notice — there is no self-service withdrawal yet, and a withdrawal does
not undo processing already done. A person who registered on their own phone
keeps a page showing their registration, their consent and, once published,
the report.

## Identifiability

* Participants can be fully pseudonymous (`P001`…). Names and emails are
  optional everywhere.
* Diarization produces `SPEAKER_NN` labels only. There is no voice biometric
  identification and no automatic real-name attribution.
* Audio itself is inherently identifiable — a voice is personal data even
  without a name attached. Retention and access control matter accordingly.

## Secrets

* Provider API keys are stored in Nextcloud's *sensitive* AppConfig and are
  never returned by any API, never written to a QR code, and never logged. UIs
  see only `configured: true` and the last four characters.
* Testing a provider connection against a typed-in endpoint requires a
  typed-in key, so a saved key cannot be sent to an arbitrary host.
* Recorder QR tokens are 256-bit random secrets. Only their SHA-256 hash is
  used for verification; a reversible copy is encrypted with the app secret so
  organisers can reprint sheets.
* A redaction processor scrubs anything matching
  `secret|token|passw|api_key|authorization|bearer|credential|cookie` from
  every log event on every sink, as defence in depth.

## Access control

* Organiser data is scoped to the Nextcloud user who created the assembly.
  Requests for someone else's assembly return 404, not 403, so the API is not
  an existence oracle.
* Table phones authenticate with a bearer token scoped to one assembly and one
  table, valid for 16 hours. A phone cannot read or write another table's
  recording.
* QR invites expire 30 days after they are generated. Revoking invites also
  disconnects devices that already joined.
* Administrator settings require Nextcloud administrator group membership,
  checked both by the AppAPI proxy and by the app itself.

## Threats we do not fully mitigate

Stated plainly, because an organisation deploying this should know:

* **A QR code is a secret printed on a poster in a public room.** Anyone who
  photographs it can join that table until the invite is revoked or expires,
  and could occupy the table's recording slot or contribute audio. Keep sheets
  with the facilitator and revoke after the event.
* **An administrator can point transcription at any endpoint**, including one
  that is not the provider participants were told about. This is an
  administrative trust boundary, not a technical one.
* **The recording device is a phone in a room.** Citizens cannot know whether
  everyone present was actually informed.

## Deleting everything for one assembly

Deleting an assembly from the organiser UI removes its recordings, transcripts,
live captions, findings, reports, exports and the phones' diagnostic logs, and
purges its storage directory. Entries already written to the rotating application log
(`logs/citizens.jsonl`) are not rewritten; they contain event names, ids and
timings, never audio or transcript text.
