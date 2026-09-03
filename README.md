# Citizens — deliberative assemblies in Nextcloud

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

A Nextcloud [ExApp](https://docs.nextcloud.com/server/latest/developer_manual/exapp_development/index.html)
for running **in-person citizens' assemblies and deliberative workshops**: one
ordinary phone per discussion table records the conversation, and the app turns
those recordings into transcripts, per-table summaries and cross-table findings
that a human organizer reviews before anything is published.

> **Beta.** The pipeline is tested end to end. Audio retention is configurable,
> and the recorder tells each table what happens to the recording before it
> starts. That screen is not a per-individual consent record, so bring your own
> privacy notice, and rehearse before a high-stakes assembly.

```text
50 citizens → 10 tables → 1 phone per table
                              │
              records locally, uploads when it can
                              │
                          Citizens
                              │
        transcription with speaker diarization (Deepgram / Mistral)
                              │
            per-table analysis → cross-table synthesis
                              │
                        human review
                              │
                     final report (PDF / MD / JSON)
```

## What it does

* **Offline-first recording.** Audio is written to the phone's storage before
  anything is uploaded, with checksums and idempotent retries, so a bad network
  can never lose a discussion.
* **Two ways to run an assembly.** *Live*: you start and end each round and every
  armed table records simultaneously. *Independent*: each table works through the
  same questions on its own schedule, even days apart.
* **Transcription that fits the room.** Four engines, two of which run entirely
  on your own hardware. Live captions and the transcription of the finished audio
  are separate switches: run both, or run captions alone and let them be the
  record — which skips a second pass over every recording, at some cost in
  accuracy that the report states plainly.
* **A dead phone does not end a table.** Batteries die mid-round. The
  facilitator hands the table to any other phone from the Live tab — or a
  replacement is let in automatically after two minutes of silence — and the
  half already recorded is transcribed and analysed with the rest, so the round
  reads as one discussion. Phones report their battery level while recording,
  so a table can be swapped before it goes dark rather than after.
* **Evidence-linked analysis.** Every finding cites the transcript passages that
  support it — speaker, timestamp, exact words. A finding with no evidence is
  discarded automatically.
* **Human-approved output.** AI findings are drafts until an organizer approves
  them; reports distinguish approved findings from AI summaries.
* **Institutional reports.** Branded PDF with an executive summary, points of
  consensus and divergence, and participation coverage — publishable back to the
  table phones so participants see their own outcome.
* **The citizens' half is translated.** The phone recorder — including the
  consent screen people tap before being recorded — is shown in the assembly's
  own language, not the phone's, because it is a shared table device. English
  and Italian today; a missing translation fails the build rather than
  appearing on somebody's phone.
* **Data you control.** Per-assembly Files tab to download, export or delete
  audio and transcripts at any time — and with a self-hosted Whisper server or
  Vosk, recordings never leave your infrastructure at all.
* **Audio can be cleared off the phones.** Recording offline-first means every
  phone keeps a copy of its table's audio, which matters when participants used
  their own devices. Once the assembly is closed, one button asks every phone
  still open to delete it, and reports how many confirmed. A phone only ever
  deletes audio the server has already accepted, so the request can never
  destroy the last copy.

## Install

Settings → Administration → **External Apps** → *Citizens* → Install.
Requires Nextcloud 32+ with AppAPI and a deploy daemon.

Then open **Citizens → Settings** to add a speech-to-text key and an analysis
endpoint. Until you do, the app records and stores audio but sends nothing
anywhere. See the [administration guide](docs/administration.md).

## What leaves your server

| Step | Data | Destination | Condition |
|---|---|---|---|
| Transcription | assembled audio of a recording | Deepgram, Mistral, or any OpenAI-compatible Whisper endpoint — **or nothing at all**, with a self-hosted Whisper server or Vosk | only with an admin-configured engine |
| Analysis | transcript text (never audio) | any OpenAI-compatible endpoint, including your own | only with an admin-configured endpoint |

Everything else — audio, transcripts, findings, reports — stays in the app's own
storage on your server, never in users' Nextcloud files.
Full note: [docs/privacy.md](docs/privacy.md).

## Documentation

* [Administration guide](docs/administration.md) — install, keys, data, troubleshooting
* [Privacy & data handling](docs/privacy.md)
* [Architecture](docs/architecture.md) — how the pipeline works
* [Development environment](docs/development-environment.md) — run it locally
* [Testing](docs/testing.md)
* [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md) · [Changelog](CHANGELOG.md)

## Licence

AGPL-3.0-or-later — see [LICENSE](LICENSE).
