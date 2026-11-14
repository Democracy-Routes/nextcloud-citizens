# Polis

**Polis** is the Democracy Routes tool for letting a large group of people say what they think in their own words, without a
meeting. People vote **agree**, **disagree** or **pass** on short statements, can write statements of their own, and the maths
finds the **opinion groups** and the statements that unite or divide them. In the Democracy Routes platform it is the public
second step after a [Citizens](../index.md) assembly: the findings an assembly approves become the **seed statements** of a
conversation that anyone with the link can vote on. See [Citizens + Polis](../bridge/index.md) for how the two connect.

The live instance is at **[polis.democracyroutes.com](https://polis.democracyroutes.com)**. The software is the
**Citizen-polis-orbis** repository, [github.com/Democracy-Routes/polisorbis](https://github.com/Democracy-Routes/polisorbis).

!!! info "These pages describe a repository by hand"
    The Polis pages are written from the repository's own documents and code (`README.md`, `docs/`, `deploy/`, `server/`). They
    are refreshed by hand when the repository changes; the [changelog](changelog.md) here is a dated copy. Where a source is
    silent, the page says less rather than guess.

## Lineage

Citizen-polis-orbis started in October 2026 from [PolisOrbis 1.5.0](https://gitlab.com/copernicani/polisorbis/codebase) by the
Copernicani association, a GDPR-oriented fork of [Polis](https://github.com/compdemocracy/polis) by the Computational Democracy
Project. The maths, the data model and the API are theirs; the Postgres and maths images in use are Copernicani's published
ones. Their copyright notices stay in the files they wrote, and the repository history contains theirs.

PolisOrbis was chosen on 2026-10-28 over upstream Polis 2 and over Agora. The recorded reasons: a classic Polis API (a small
bridge), an EU orientation with most third-party calls already removed, and the smallest memory footprint. Upstream Polis 2 would
have meant removing AWS, Anthropic, Auth0 and Simple Analytics and following a fast-moving codebase; Agora is a separate product
with US subprocessors and trademarked branding. The hosted pol.is service is out: Polis is self-hosted, in Europe, and must be
GDPR friendly (owner decision, 2026-10-28).

## What is different in the fork

| Area | What the fork does |
|---|---|
| Voting page | The democracyroutes.com look. On phones an app-style page with four panes (vote, write, groups, info), a bottom tab bar, no page scrolling, and swipe to vote (right agrees, left disagrees). Tablets, laptops and embeds keep the classic layout. |
| Report | Rebuilt for phones and laptops: a summary first, one section per screen on phones, statement rows as stacked bars per opinion group, a zoomable opinion map, English and Italian. The numbers are the ones Polis computes. |
| Organizer pages | One top bar, a card list of conversations, three sections per conversation (Set up, Moderate, Results), phone layouts, a copy link and live numbers. |
| Seed statements from Citizens | `POST /api/v3/citizens/import` creates a conversation, its report and the seeds in one call, with an API key. Also a CSV upload (`comments-bulk`) and a textarea. |
| AI drafting | Statement drafts from any OpenAI-compatible provider. Off until a provider is configured. |
| Home page | Lists the open conversations an organizer chose to show, with a Vote button and the results link. |
| Legal pages | Built-in privacy and terms pages (English, Italian) filled from operator variables. |
| Third parties | No requests to third parties from any page; fonts are self-hosted. |
| Purge | PolisOrbis's sandbox purge is off; see [Deployment](deployment.md#the-purge-and-the-data-loss-of-2-november-2026). |
| Self-hosting kit | One script for the local or production stack with a memory cap on every container, one to build images, one to apply database changes, scripts for team accounts and API keys, and an nginx site that blocks public sign-up. |

## Status

* **Live** since 2026-10-29 at polis.democracyroutes.com, on the shared host behind its nginx.
* **Backups do not exist yet** (see [Deployment](deployment.md#backups)). Treat the instance's data as not recoverable.
* The organizer pages are English only. The voting page ships 22 UI languages (browser language or `?ui_lang=xx`; Italian is
  partial, 68 of 121 strings). The report and the legal pages are English and Italian (`?lang=it`).
* The repository's `CONTRIBUTING.md` says only that a Contributing Agreement is expected soon.

## Licence

AGPL-3.0. Section 13 applies: the public instance links to this source in its footer, so an installation that changes the code
must publish its changes. New files carry `SPDX-License-Identifier: AGPL-3.0-or-later`.

## Where to go next

| I want to... | Read |
|---|---|
| Understand the vocabulary | [Concepts](concepts.md) |
| Run a conversation | [Running a conversation](organizers.md) |
| Host my own Polis | [Deployment](deployment.md) and [Configuration variables](configuration.md) |
| Know what is stored and what leaves the server | [Privacy](privacy.md) |
| Call the API | [API reference](api.md) |
| See how it is built | [Architecture](architecture.md) |
| Send assembly statements to Polis | [Citizens + Polis](../bridge/index.md) |
