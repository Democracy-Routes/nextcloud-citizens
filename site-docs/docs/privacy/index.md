# Privacy and security

Citizens records people's voices, which is sensitive personal data. This section describes **what the
software actually does today**, so that an organisation deploying it can write its own privacy notice and
processing record against something accurate. Where a control does not exist yet, it says so. It is
condensed from the repository's `docs/privacy.md`.

## What is stored, and where

Everything Citizens stores lives under the app's own persistent storage (`APP_PERSISTENT_STORAGE`, mounted
at `/data`):

| Data | Location | Notes |
|---|---|---|
| Audio recordings | `assembled/` | one file per table per round |
| Upload chunks | `recordings/` | **deleted automatically** once the assembled file is verified; `manifest.json` keeps each chunk's checksum as the audit trail |
| Transcripts | `transcripts/` and the database | segments and words, with speaker labels |
| Live captions | `live_captions/` | what a caption session heard, written when it ends; becomes the transcript when final transcription is off |
| Findings and reports | database | AI drafts plus human review decisions |
| Device diagnostics | `logs/devices/` | phone-side event log, capped at 5 MB per session |
| Application log | `logs/citizens.jsonl` | rotated, 10 MB x 5 |

Citizens never reads or writes Nextcloud user files. In standalone mode, organizer accounts are stored in
the app database: a username, a display name, an email address and a password hash. Invitation and
password-reset links are stored hashed and expire. Deleting an account removes the account and its links.

## What leaves the server

Nothing, until an administrator configures a provider. Hosted engines (Deepgram, Mistral) receive the
assembled audio of each recording once; Whisper against your own endpoint and Vosk keep audio on your
infrastructure; analysis receives transcript text only, never audio; Polis receives approved statement text
only when an organizer presses Send to Polis; live captions use the same engine as transcription and, when a
session ends, what it heard is written to `live_captions/`. The full table is in
[Providers and egress](../admin/providers-egress.md). The recorder tells each table which of these applies
before recording starts; see [Consent and the notice](consent.md).

## Retention

* Raw audio retention is a number of days after an assembly is **closed**; `0` keeps it indefinitely, the
  default. Individual assemblies can override the instance default. Deletion runs from a periodic sweep, is
  audit-logged (assembly, policy, number of recordings, bytes freed) and never logs content.
* **Zero retention** keeps only the report: audio, every transcript and the live-caption files are deleted
  outright once the assembly is closed and every transcription and analysis has finished, and a PDF of the
  frozen report is kept. Nothing but the participant list and that PDF survives. It cannot be undone and the
  assembly can never be reopened.
* **Audio that arrives after a recording has been closed is not lost (0.7).** It opens a new recording of the
  same table and recorder, which is ordinary audio from there on, subject to retention like any other.
* **Audio only.** Transcripts, findings and reports are the record of the assembly and are not touched by
  retention. Delete them explicitly from the Files tab.
* Organizers can delete audio and transcripts at any time, and deleting an assembly deletes its audio,
  transcripts, live captions and exports. Deleting one table's transcript deletes that table's live captions
  too: the same speech in a second file.
* Deleting audio, by hand or by the sweep, also deletes that assembly's **export archives**, which hold a
  complete second copy of the recordings. Archives nobody collected are swept after an hour.
* **The table phones hold a copy too.** Every recording is written to the phone's storage before upload, so at
  the end each phone still has its table's audio. When participants use their own devices, **those devices are
  a processing location outside your control**; say so in your own privacy information. Closing the session
  asks phones to clear their copy (on by default, switchable per assembly), and the Files tab has **Clear audio
  from the table phones**. It reaches phones whose recorder page is open, and a phone only deletes recordings
  the server has confirmed it holds.
* **Sessions that never recorded, and spent single-use QR codes, are removed a week after they expired (0.7)**,
  including that phone's device log. A session that did make a recording is kept, because it is that
  recording's record of which phone made it.
* **Polis seeds are statement text only**: no evidence, quotations, transcript text, table numbers, participant
  data or Citizens ids. Seeds are deleted with the assembly; a statement can be deleted on its own.
* **Not implemented:** there is no automatic deletion of transcripts or findings, and no data-subject-request
  tooling. Both are manual today.

## Imported archives and attached files { #imported-archives-and-attached-files }

An organizer can import a session export from another server, or attach an audio file or transcript to a
recording. An imported archive carries transcripts (conversation content) and participant data; once imported,
they are this server's data under the same retention and deletion rules as a live session. Findings and the
report in an archive are not copied. Upload parts stay in temp storage until the import completes or the
housekeeping sweep removes them after 24 hours. Attaching a transcript means the organizer had the conversation
transcribed elsewhere; Citizens records provider and model as given in the file and cannot verify them. Imports
and attachments are audit-logged (`session_imported`, `transcript_attached`, `audio_attached`).

## Identifiability

* Participants can be fully pseudonymous (`P001`...). Names and emails are optional everywhere.
* Diarization produces `SPEAKER_NN` labels only. There is no voice biometric identification and no automatic
  real-name attribution.
* Audio itself is inherently identifiable: a voice is personal data even without a name attached. Retention and
  access control matter accordingly.
* Names people say out loud are in the transcript; see [Pseudonyms and names](pseudonyms.md).

## Secrets

* Provider API keys are stored as sensitive configuration and are never returned by any API, never written to a
  QR code and never logged. Interfaces see only `configured: true` and the last four characters.
* Testing a provider connection against a typed-in endpoint requires a typed-in key, so a saved key cannot be
  sent to an arbitrary host.
* Recorder QR tokens are 256-bit random secrets. Only their SHA-256 hash is used for verification; a reversible
  copy is encrypted with the app secret so organisers can reprint sheets.
* A redaction processor scrubs anything matching `secret|token|passw|api_key|authorization|bearer|credential|cookie`
  from every log event on every sink.

## Access control

* Organiser data is scoped to the user who created the assembly. Requests for someone else's assembly return 404,
  not 403, so the API is not an existence oracle.
* Table phones authenticate with a bearer token scoped to one assembly and one table, valid for 16 hours from the
  phone's last contact. A phone cannot read or write another table's recording.
* QR invites expire 30 days after they are generated. Revoking invites also disconnects devices that already
  joined.
* Administrator settings require administrator membership, checked both by the AppAPI proxy and by the app (in
  Nextcloud mode).
* A facilitator's phone follows one table through a code the table's phone shows. The server keeps only a hashed
  bearer with the table number and timestamps: no name, no audio, no captions.

## Threats we do not fully mitigate

Stated plainly, because an organisation deploying this should know.

!!! warning "A QR code is a secret printed on a poster in a public room"
    Anyone who photographs it can join that table until the invite is revoked or expires, and could occupy the
    table's recording slot or contribute audio. Keep sheets with the facilitator and revoke after the event.

* **An administrator can point transcription at any endpoint**, including one that is not the provider
  participants were told about. This is an administrative trust boundary, not a technical one.
* **The recording device is a phone in a room.** Citizens cannot know whether everyone present was actually
  informed.
* **Names spoken aloud reach the transcription provider** in the audio; masking protects only the analysis step.
* No software guarantees capture through a dead battery, a killed browser or erased browser storage; see
  [Recording pipeline and reliability](../architecture/recording-pipeline.md).

## Deleting everything for one assembly { #deleting-everything-for-one-assembly }

Deleting an assembly from the organiser interface removes its recordings, transcripts, live captions, findings,
reports, exports and the phones' diagnostic logs, and purges its storage directory. Entries already written to
the rotating application log (`logs/citizens.jsonl`) are not rewritten; they contain event names, ids and timings,
never audio or transcript text.
