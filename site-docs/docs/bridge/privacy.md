# Privacy across the bridge

This page shows what crosses from Citizens to Polis, what stays, and who is responsible. Each tool's own page covers the rest:
[Citizens privacy](../privacy/index.md) and [Polis privacy](../polis/privacy.md).

## What crosses

| Datum | Crosses to Polis | Notes |
|---|---|---|
| Approved statement text | Yes | Public once on Polis: other participants vote on it |
| Statement positions | Yes | The order in the export |
| Assembly name | Yes | Becomes the conversation's topic, public on the voting page and, if listed, on the home page |
| Assembly description | Yes | Cut to 2000 characters; shown under the title |
| Assembly language | Yes | Recorded, not used by Polis |
| Export time | Yes | Part of the file |
| Findings, evidence, transcript excerpts, the Why trail | No | The Why panel's excerpt is for the organizer only |
| Audio, speaker labels, participant data, table numbers, Citizens ids | No | The file carries no such field |

Nothing is sent back from Polis except the conversation id, the three links and the per-statement result. No vote, participant or
cookie crosses in either direction.

## Two lines of defence

1. Citizens writes statements to a style card: no names, no table numbers, no quotations, no "our table". The organizer reads
   and approves every statement before anything leaves.
2. Polis refuses the whole call if a statement contains an e-mail address, a phone number, a table reference or is wrapped in
   quotation marks; see [Contract](contract.md#rules). The refused statements are marked in Citizens.

Neither rule can recognize a name written into a sentence. The organizer's review is the control for that.

!!! warning "The organizer is responsible for what is published"
    Statements and the assembly name and description become public on Polis, in a conversation anyone with the link can read and vote
    on. Read the statements, the name and the description as if they were already published.

## Anonymous, open voting

Polis voting is open to anyone with the link. Participants have no account and no name; a random cookie identifies a browser so that
votes count once. Votes are never linked to a table or to a person in the assembly: Citizens sends no table or participant
information, and Polis has nowhere to store it. The people in the room vote the same way as anyone else, by scanning a QR code.
Participant codes (an external id per participant) are not supported; see [Roadmap](roadmap.md).

Votes on statements about public issues can reveal political opinions (GDPR Art. 9). The Polis privacy notice tells
participants what is recorded and states consent by voting after reading it.

## Consent context for assemblies

The consent a table gives in Citizens is recorded against the Citizens [notice](../privacy/consent.md), which concerns the recording
and its processing. Treat Polis voting as a separate, public and anonymous act with its own notice on Polis. Say so in your own
information to participants: the statements derived from their discussion will be published, in anonymised form, for a wider vote.

## Where each datum lives

| Datum | Lives in |
|---|---|
| Audio, transcripts, findings, statement drafts and the Why trail | Citizens (its storage and database) |
| The conversation id, three links, push time and per-statement `tid` | Citizens database, deleted with the assembly |
| API key (Polis side) | Polis database; revoked with `delete-apikey.sh` |
| API key (Citizens side) | Citizens Settings, stored as sensitive configuration, never returned by any API or logged |
| Conversation, statements, votes, participant cookies | Polis database, kept until the conversation is deleted by hand (the purge is off) |

Deleting an assembly in Citizens deletes its seeds and the stored links; it does not delete the Polis conversation. Withdrawing
the poll from the devices does not close it either. Close or delete it on Polis.
