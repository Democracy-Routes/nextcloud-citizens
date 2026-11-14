# Citizens documentation

Citizens runs **in-person citizens' assemblies and deliberative workshops**. One
ordinary phone per discussion table records the conversation. The app turns those
recordings into transcripts, per-table summaries and cross-table findings, and a
human organizer reviews all of it before anything is published.

!!! warning "Status: beta"
    The pipeline is tested end to end. Audio retention is configurable, down to
    **zero retention** (keep only the report, nothing recorded behind it). The
    recorder tells each table what happens to the recording before it starts, and
    records each person's individual consent against that notice (on the table's
    phone or on their own). Set the data controller and contact in Settings, have
    counsel read the notice if you are a public body, and rehearse before a
    high-stakes assembly.

## Who it is for

* **Organizers** who run an assembly: plan sessions, print the QR sheet, watch the
  tables live, review the findings and publish a report. Start with
  [Running an assembly](organizers/index.md).
* **Facilitators** who sit at one table with their own phone. See the
  [facilitator guide](organizers/facilitator.md).
* **Administrators and operators** who install the app, configure speech-to-text and
  analysis providers, back it up and keep it running. See
  [Administration](admin/index.md).
* **Data-protection officers and counsel** who need to know what is stored, what
  leaves the server and what consent is recorded. See
  [Privacy and security](privacy/index.md).
* **Developers** who extend or integrate it. See [Architecture](architecture/index.md),
  the [API reference](reference/api/index.md) and [Contributing](contributing/index.md).

## How it works

```text
50 citizens -> 10 tables -> 1 phone per table
                              |
              records locally, uploads when it can
                              |
                          Citizens
                              |
        transcription with speaker diarization (Deepgram / Mistral)
                              |
            per-table analysis -> cross-table synthesis
                              |
                        human review
                              |
                     final report (PDF / MD / JSON)
```

Audio is written to the phone's storage before anything is uploaded, with checksums
and idempotent retries, so a bad network does not lose a discussion. Every finding
cites the transcript passages that support it (speaker, timestamp, exact words); a
finding with no evidence is discarded automatically. AI findings are drafts until an
organizer approves them, and reports distinguish approved findings from AI summaries.

Transcription has four engines: Deepgram, Mistral (Voxtral), any OpenAI-compatible
Whisper endpoint, and Vosk, which can run built into the app. Two of them can run
entirely on your own hardware, so recordings never have to leave your infrastructure.
See [Providers and egress](admin/providers-egress.md).

## Two ways to run it

| | Nextcloud ExApp | Standalone |
|---|---|---|
| What it is | A container that Nextcloud 32+ runs through AppAPI and proxies | The same app in one Docker container behind your own reverse proxy |
| Organizer sign-in | Nextcloud users | Accounts in the app |
| Settings stored in | Nextcloud's app configuration | The app database |
| Install | External Apps, or `occ app_api:app:register` | `sh scripts/standalone-up.sh` |
| Guide | [Install as a Nextcloud ExApp](getting-started/install-nextcloud.md) | [Run standalone](getting-started/standalone.md) |

Recording, transcription, analysis and reports work the same way in both modes.

## Where to go next

| I want to... | Read |
|---|---|
| Check what I need before installing | [Requirements](getting-started/requirements.md) |
| See the whole flow once | [First assembly in 15 minutes](getting-started/first-assembly.md) |
| Prepare a real event | [Before the day](organizers/before-the-day.md) and [On the day](organizers/on-the-day.md) |
| Turn findings into a Polis conversation | [Polis consultation](organizers/polis.md) |
| Configure providers and keys | [Settings reference](admin/settings.md) |
| Know what leaves the server | [Providers and egress](admin/providers-egress.md) and the [data map](privacy/index.md) |
| Look up a route | [API reference](reference/api/index.md) |
| Fix a problem | [Troubleshooting](admin/troubleshooting.md) |

Citizens is licensed under AGPL-3.0-or-later. The source is at
[github.com/Democracy-Routes/nextcloud-citizens](https://github.com/Democracy-Routes/nextcloud-citizens).
