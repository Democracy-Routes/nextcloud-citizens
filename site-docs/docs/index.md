# Democracy Routes documentation

**Democracy Routes** builds open-source tools for democratic participation. This site documents the platform's two programs and
the bridge between them:

* **Citizens** runs in-person citizens' assemblies and deliberative workshops. One ordinary phone per discussion table records the
  conversation; the app produces transcripts, per-table summaries and cross-table findings, and a human organizer reviews all of it
  before anything is published. Source: [github.com/Democracy-Routes/nextcloud-citizens](https://github.com/Democracy-Routes/nextcloud-citizens).
* **Polis** lets a wide public vote **agree**, **disagree** or **pass** on short statements, and maps the opinion groups and the
  statements that unite or divide them. The Democracy Routes fork, Citizen-polis-orbis, runs at
  [polis.democracyroutes.com](https://polis.democracyroutes.com). Source:
  [github.com/Democracy-Routes/polisorbis](https://github.com/Democracy-Routes/polisorbis).
* **The bridge** takes the findings an assembly approves, writes them up as seed statements, and sends them to a Polis conversation
  that the people in the room, and anyone else with the link, can vote on.

```text
  CITIZENS                                              POLIS
  50 citizens -> 10 tables -> 1 phone per table
        |
  recordings -> transcripts -> findings
        |
  organizer review (approve findings)
        |
  seed statements (ground, draft, critique)
        |
  organizer review (approve statements)
        |
  Send to Polis ----- statement text only ------->  conversation + report
        |                                                  |
  poll on the table phones (link + QR) ----------->  anyone with the link votes
        |                                                  |
  Citizens report (PDF / MD / JSON)   <-- roadmap --  opinion groups, consensus
```

Citizens and Polis also work alone. The arrows labelled "roadmap" are **not built**: Polis results do not yet flow back into the
Citizens report. See [Citizens + Polis](bridge/index.md).

!!! warning "Citizens status: beta"
    The pipeline is tested end to end. Audio retention is configurable, down to **zero retention** (keep only the report, nothing
    recorded behind it). The recorder tells each table what happens to the recording before it starts, and records each person's
    individual consent against that notice (on the table's phone or on their own). Set the data controller and contact in Settings,
    have counsel read the notice if you are a public body, and rehearse before a high-stakes assembly.

!!! warning "Polis status: no backups"
    The Polis instance has **no backups yet**, and a purge job once deleted conversations (since stopped). Do not treat its data as
    recoverable. See [Polis deployment](polis/deployment.md#backups).

## Who it is for

| You are... | Start here |
|---|---|
| An **organizer** running an assembly | [Running an assembly](organizers/index.md) |
| A **facilitator** at one table | [Facilitator guide](organizers/facilitator.md) |
| An **administrator or operator** of Citizens | [Administration](admin/index.md) and [Getting started](getting-started/index.md) |
| A **Polis owner** running a conversation | [Running a conversation](polis/organizers.md) |
| An **operator** hosting Polis | [Polis deployment](polis/deployment.md) and [configuration](polis/configuration.md) |
| Connecting the two | [Citizens + Polis](bridge/index.md) and [Connecting an installation](bridge/setup.md) |
| **Data-protection officer or counsel** | [Citizens privacy](privacy/index.md), [Polis privacy](polis/privacy.md), [Privacy across the bridge](bridge/privacy.md) |
| A **developer** | [Citizens architecture](architecture/index.md), [Citizens API](reference/api/index.md), [Polis architecture](polis/architecture.md), [Polis API](polis/api.md), [bridge contract](bridge/contract.md), [Contributing](contributing/index.md) |

## Citizens: how it works

Audio is written to the phone's storage before anything is uploaded, with checksums and idempotent retries, so a bad network does
not lose a discussion. Every finding cites the transcript passages that support it (speaker, timestamp, exact words); a finding
with no evidence is discarded automatically. AI findings are drafts until an organizer approves them, and reports distinguish
approved findings from AI summaries. Transcription has four engines: Deepgram, Mistral (Voxtral), any OpenAI-compatible Whisper
endpoint, and Vosk, which can run built into the app; two of them run on your own hardware. See
[Providers and egress](admin/providers-egress.md).

| | Nextcloud ExApp | Standalone |
|---|---|---|
| What it is | A container that Nextcloud 32+ runs through AppAPI and proxies | The same app in one Docker container behind your own reverse proxy |
| Organizer sign-in | Nextcloud users | Accounts in the app |
| Settings stored in | Nextcloud's app configuration | The app database |
| Install | External Apps, or `occ app_api:app:register` | `sh scripts/standalone-up.sh` |
| Guide | [Install as a Nextcloud ExApp](getting-started/install-nextcloud.md) | [Run standalone](getting-started/standalone.md) |

## Polis: what it adds

The fork keeps the Polis engine and rebuilds the voting page (swipe to vote on phones), the report, the organizer pages, the
deployment and the way statements get in: a CSV upload, AI drafting, and one import call for Citizens. No page loads anything from a
third party. See [Polis](polis/index.md).

## Where to go next

| I want to... | Read |
|---|---|
| Check what I need before installing Citizens | [Requirements](getting-started/requirements.md) |
| See the whole Citizens flow once | [First assembly in 15 minutes](getting-started/first-assembly.md) |
| Prepare a real event | [Before the day](organizers/before-the-day.md) and [On the day](organizers/on-the-day.md) |
| Turn findings into a Polis conversation | [Polis consultation](organizers/polis.md) |
| Understand the whole Citizens + Polis path | [Citizens + Polis](bridge/index.md) |
| Connect Citizens to a Polis instance | [Connecting an installation](bridge/setup.md) |
| Learn what Polis is and how it differs from upstream | [Polis](polis/index.md) and [Concepts](polis/concepts.md) |
| Host Polis myself | [Polis deployment](polis/deployment.md) |
| Configure providers and keys | [Settings reference](admin/settings.md) |
| Know what leaves the server | [Providers and egress](admin/providers-egress.md), the [Citizens data map](privacy/index.md), [Polis privacy](polis/privacy.md) |
| Look up a route | [Citizens API](reference/api/index.md) or [Polis API](polis/api.md) |
| See what is planned and not built | [Roadmap](bridge/roadmap.md) |
| Fix a problem | [Troubleshooting](admin/troubleshooting.md) |

Both programs are licensed under AGPL. Citizens is AGPL-3.0-or-later; Polis (Citizen-polis-orbis) is AGPL-3.0, with section 13
applying to the public instance.
