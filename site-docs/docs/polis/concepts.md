# Concepts

The vocabulary of Polis: conversations, statements, votes, moderation and opinion groups.

## Conversation

A conversation is one consultation: a topic, an optional description, a set of statements, and the votes
on them. It has a short public id (for example `3hjm3feewj`). The voting page is
`https://<instance>/<id>`, the moderation pages are at `https://<instance>/m/<id>` and the report is at
`https://<instance>/report/<report id>`.

One team account owns a conversation. It can be open or closed, and a draft or not. Anyone with the link
can vote. Participants need no account and are never asked for a name.

## Statements

A statement is a short sentence that people vote on. The code and the API call it a comment, with `txt` as
its text. A participant can also write statements of their own. Statements are public, and other
participants vote on them.

Statements added through the CSV route and the Citizens import are 1 to 400 characters. The server accepts
up to 997 characters through `POST /api/v3/comments`. The participation client has its own limit that the
sources do not state.

## Seed statements

A seed statement is one the organizer adds before anyone votes, so that participants have something to
react to. Seeds are stored with `is_seed: true`. You can add them by hand in the Set up page, by CSV
upload, by AI drafting (reviewed first) and, from a Citizens assembly, by the import call. The same text
is never added twice to a conversation.

## Votes

A participant votes agree, disagree or pass on each statement. On phones the voting page also accepts a
swipe: right agrees, left disagrees. A random identifier kept in a browser cookie (`pc`) identifies the
participant, so votes are counted once and a statement is not shown twice. The identifier is not linked to
a name.

## Moderation

The Moderate section of a conversation has three queues: to review, accepted and rejected. Moderators are
the conversation's owner and any moderators they add. A conversation can be created with strict
moderation: the import call takes a `strict_moderation` field, default `false`. The sources do not
describe its behavior beyond naming the option.

## Opinion groups and consensus

The math service reads the vote matrix and finds opinion groups, sets of participants who voted alike.
The report shows, per statement, a stacked bar per group (agree, disagree, pass, did not see) and
highlights four things:

* the strongest consensus, the statement most agreed across groups;
* the most divisive statement;
* the groups themselves, on a zoomable opinion map;
* the uncertainty of the picture.

Groups are named "Group A", "Group B" and so on. Custom names set on the report (`label_group_N`) are used
everywhere. The fork changed only the presentation of the report; the numbers are the ones PolisOrbis
computes, and the groups are computed from votes only.

## Owners and participants

| | Owner (team account) | Participant |
|---|---|---|
| Account | Yes, created by the operator with a script | None |
| Can create conversations | Yes | No |
| Can vote and write statements | Yes | Yes, with the link |
| Identified by | A hashed e-mail and a password | A random cookie |

Public sign-up is blocked at the proxy. See [Running a conversation](organizers.md#team-accounts).

## Listed conversations

An owner can switch on Appear on the home page of this site for a conversation. While the conversation is
open, `/home` lists it with its title, description, participant count, a Vote button and, when a report
exists, the results link. Nothing is listed unless an organizer switches it on. The list comes from the
public [`GET /api/v3/listed-conversations`](api.md#get-apiv3listed-conversations).
