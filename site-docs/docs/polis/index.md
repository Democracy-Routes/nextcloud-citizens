# Polis

Polis lets a large group of people say what they think without a meeting. After reading this section you can
run a conversation, host your own instance, or connect it to a Citizens assembly.

People vote agree, disagree or pass on short statements and can write statements of their own. The math
then finds the opinion groups and the statements that unite or divide them. In the Democracy Routes
platform, Polis is the public second step after a [Citizens](../index.md) assembly: the findings an
assembly approves become the seed statements of a conversation that anyone with the link can vote on. The
[Citizens + Polis](../bridge/index.md) section describes how the two connect.

The live instance is at [polis.democracyroutes.com](https://polis.democracyroutes.com). The software is the
Citizen-polis-orbis repository, [github.com/Democracy-Routes/polisorbis](https://github.com/Democracy-Routes/polisorbis).

## Lineage

Citizen-polis-orbis starts from [PolisOrbis 1.5.0](https://gitlab.com/copernicani/polisorbis/codebase) by
the Copernicani association, itself a fork of [Polis](https://github.com/compdemocracy/polis) by the
Computational Democracy Project. The math, the data model and the API are theirs, and their copyright
notices stay in the files they wrote.

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

## Languages

The organizer pages are English only. The voting page ships 22 UI languages, chosen by browser language or
`?ui_lang=xx`; Italian is partial, 68 of 121 strings. The report and the legal pages are English and
Italian (`?lang=it`).

The instance has no backups; see [Deployment](deployment.md#backups). The repository's `CONTRIBUTING.md`
says only that a Contributing Agreement is expected soon.

## License

Polis is released under AGPL-3.0. Section 13 applies: the public instance links to this source in its
footer, so an installation that changes the code must publish its changes. New files carry
`SPDX-License-Identifier: AGPL-3.0-or-later`.

## Where to go next

* [Concepts](concepts.md) explains the vocabulary.
* [Running a conversation](organizers.md) covers the organizer pages.
* [Deployment](deployment.md) and [Configuration variables](configuration.md) cover hosting your own Polis.
* [Privacy](privacy.md) lists what is stored and what leaves the server.
* [API reference](api.md) lists the routes.
* [Architecture](architecture.md) describes how it is built.
* [Citizens + Polis](../bridge/index.md) explains how to send assembly statements to Polis.
