# Democracy Routes documentation

Democracy Routes builds open-source tools for democratic participation. This site documents two
programs and the bridge between them, and points you to the page you need.

Citizens runs in-person citizens' assemblies and deliberative workshops. One ordinary phone per
discussion table records the conversation. The app produces transcripts, per-table summaries and
cross-table findings, and a human organizer reviews all of it before anything is published. Source:
[github.com/Democracy-Routes/nextcloud-citizens](https://github.com/Democracy-Routes/nextcloud-citizens).

Polis lets a wide public vote agree, disagree or pass on short statements. It maps the opinion groups
and the statements that unite or divide them. The Democracy Routes fork, Citizen-polis-orbis, runs at
[polis.democracyroutes.com](https://polis.democracyroutes.com). Source:
[github.com/Democracy-Routes/polisorbis](https://github.com/Democracy-Routes/polisorbis).

The bridge takes the findings an assembly approves, writes them up as seed statements and sends them
to a Polis conversation. The people in the room, and anyone else with the link, can vote on it.

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

Citizens and Polis also work alone. The arrows labeled "roadmap" are not built: Polis results do not
yet flow back into the Citizens report. See [Citizens + Polis](bridge/index.md).

Citizens is in beta. The pipeline is tested end to end. Audio retention is configurable, down to zero
retention, where only the report is kept and nothing recorded behind it. Before a table starts, the
recorder tells it what happens to the recording and records each person's individual consent against
that notice, on the table's phone or on their own. Set the data controller and contact in Settings,
have counsel read the notice if you are a public body, and rehearse before a high-stakes assembly.

!!! warning "Polis status: no backups"
    The Polis instance has no backups yet, and a purge job once deleted conversations (since
    stopped). Do not treat its data as recoverable. See
    [Polis deployment](polis/deployment.md#backups).

## Who it is for

Organizers running an assembly start with [Running an assembly](organizers/index.md). Facilitators at
a table read the [Facilitator guide](organizers/facilitator.md). Administrators and operators of
Citizens need [Administration](admin/index.md) and [Getting started](getting-started/index.md).

Polis owners running a conversation read [Running a conversation](polis/organizers.md). Operators
hosting Polis read [Polis deployment](polis/deployment.md) and [configuration](polis/configuration.md).
To connect the two programs, read [Citizens + Polis](bridge/index.md) and
[Connecting an installation](bridge/setup.md).

Data-protection officers and counsel should read [Citizens privacy](privacy/index.md),
[Polis privacy](polis/privacy.md) and [Privacy across the bridge](bridge/privacy.md).

Developers start with the [Citizens architecture](architecture/index.md), the
[Citizens API](reference/api/index.md), the [Polis architecture](polis/architecture.md), the
[Polis API](polis/api.md), the [bridge contract](bridge/contract.md) and
[Contributing](contributing/index.md).

## Citizens

Audio is written to the phone's storage before anything is uploaded, with checksums and idempotent
retries, so a bad network does not lose a discussion. Every finding cites the transcript passages that
support it (speaker, timestamp, exact words), and a finding with no evidence is discarded
automatically. AI findings are drafts until an organizer approves them, and reports distinguish
approved findings from AI summaries.

Transcription has four engines: Deepgram, Mistral (Voxtral), any OpenAI-compatible Whisper endpoint,
and Vosk, which can run built into the app. Two of them run on your own hardware. See
[Providers and egress](admin/providers-egress.md).

You can install Citizens in two ways. The standalone install runs the app in one Docker container
behind your own reverse proxy. Organizers sign in with accounts in the app, and Settings are stored in
the app database. Install it with `sh scripts/standalone-up.sh`; the guide is
[Install with Docker Compose](getting-started/standalone.md).

The Nextcloud ExApp is a container that Nextcloud 32 or newer runs through AppAPI and proxies.
Organizers sign in with their Nextcloud users, and Settings live in Nextcloud's app configuration.
Install it from External Apps or with `occ app_api:app:register`; the guide is
[Install as a Nextcloud ExApp](getting-started/install-nextcloud.md).

## Polis

The fork keeps the Polis engine and rebuilds the voting page (swipe to vote on phones), the report,
the organizer pages, the deployment and the way statements get in: a CSV upload, AI drafting, and one
import call for Citizens. No page loads anything from a third party. See [Polis](polis/index.md).

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

Both programs are licensed under AGPL. Citizens is AGPL-3.0-or-later. Polis (Citizen-polis-orbis) is
AGPL-3.0, with section 13 applying to the public instance.
