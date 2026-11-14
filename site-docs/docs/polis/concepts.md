# Concepts

## Conversation

A **conversation** is one consultation: a topic, an optional description, a set of statements, and the votes on them. It has a
short public id (for example `3hjm3feewj`); the voting page is `https://<instance>/<id>`, the moderation pages
`https://<instance>/m/<id>` and the report `https://<instance>/report/<report id>`.

A conversation is **owned** by one team account. It can be open or closed, and a draft or not. Voting is open to anyone with the
link: participants need no account and are never asked for a name.

## Statements

A **statement** (the code and API call it a *comment*, with `txt` as its text) is a short sentence that people vote on. A
participant can also write statements of their own. Statements are public: other participants vote on them.

Limits in this fork: statements added through the CSV route and the Citizens import are 1 to 400 characters. The server accepts
up to 997 characters through `POST /api/v3/comments`, and the participation client has its own limit that the sources do not
state.

## Seed statements

A **seed statement** is a statement the organizer puts in before anyone votes, so that participants have something to react to.
They are stored with `is_seed: true`. There are four ways to add them: by hand in the Set up page, by CSV upload, by AI drafting
(reviewed first) and, from a Citizens assembly, by the import call. The same text is never added twice to a conversation.

## Votes

A participant votes **agree**, **disagree** or **pass** on each statement. On phones the voting page also accepts a swipe: right
agrees, left disagrees. A participant is identified only by a random identifier kept in a browser cookie (`pc`), so votes are
counted once and a statement is not shown twice; it is not linked to a name.

## Moderation

The **Moderate** section of a conversation has three queues: **to review**, **accepted** and **rejected**. Moderators are the
conversation's owner and any moderators they add. A conversation can be created with *strict moderation* (the import call takes a
`strict_moderation` field, default `false`); the sources do not describe its behaviour beyond naming the option.

## Opinion groups and consensus

The maths service reads the vote matrix and finds **opinion groups**: sets of participants who voted alike. The **report** then
shows, per statement, a stacked bar per group (agree, disagree, pass, did not see) and highlights:

* the **strongest consensus**, the statement most agreed across groups;
* the **most divisive** statement;
* the **groups** themselves, on a zoomable opinion map;
* the **uncertainty** of the picture.

Groups are named "Group A", "Group B" and so on; custom names set on the report (`label_group_N`) are used everywhere. The
fork changed only the presentation of the report; the numbers are the ones PolisOrbis computes. The opinion groups are computed
from votes only.

## Owners and participants

| | Owner (team account) | Participant |
|---|---|---|
| Account | Yes, created by the operator with a script | None |
| Can create conversations | Yes | No |
| Can vote and write statements | Yes | Yes, with the link |
| Identified by | A hashed e-mail and a password | A random cookie |

Public sign-up is blocked at the proxy. See [Running a conversation](organizers.md#team-accounts).

## Listed conversations

An owner can switch **Appear on the home page of this site** on for a conversation. While it is open, it is listed on `/home` with
its title, description, participant count, a Vote button and, when a report exists, the results link. Nothing is listed unless an
organizer switches it on. The list comes from the public [`GET /api/v3/listed-conversations`](api.md#get-apiv3listed-conversations).
