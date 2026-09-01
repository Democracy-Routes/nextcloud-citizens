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

## What leaves the server

**Nothing, until an administrator configures a provider.** A fresh install
performs no transcription and no analysis.

* **Speech to text.** Deepgram and Mistral are hosted services: with those, the
  assembled audio of each recording is sent to the provider once. **Whisper**
  works against any OpenAI-compatible endpoint, including one you run yourself,
  and **Vosk** runs entirely offline — with either, audio never leaves your
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

This is an *information and confirmation* step at the table. It is **not** a
per-individual consent record: Citizens does not store who agreed. If your
lawful basis requires individual consent records, collect them separately.

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
