# Citizens + Polis

Citizens records and analyses an assembly of a few dozen people at tables. Polis lets a much larger public vote on short
statements and shows where they agree. The bridge turns the first into the input of the second: the findings an assembly approves
become the **seed statements** of a Polis conversation that anyone with the link can vote on, including the people in the room, on
their own phones.

After reading this section you can connect a Citizens installation to a Polis instance and send an assembly's approved statements for
a public vote.

The two are separate programs, in separate repositories, run separately. The bridge is a small one-way contract: Citizens calls
Polis. Polis never calls Citizens, and Citizens exposes no API to it.

## The flow

```text
 CITIZENS (assembly)                                                POLIS (public vote)
 -------------------                                                -------------------
 assembly at tables, one phone per table
        |
 recordings -> transcripts (speakers, timestamps)
        |
 per-table analysis -> cross-table findings, each citing transcript passages
        |
 organizer review: findings APPROVED / edited / rejected
        |
 seed statements, three passes: ground -> draft -> critique   (Why trail on each)
        |
 organizer review of the statements: edit, approve, reject, reorder, add
        |
 "Send to Polis"  ---- POST /api/v3/citizens/import, statement text only ---->  conversation created
        |                                                                       (public, with report)
        |   <---- conversation id, voting / moderation / report links ----      seeds added, idempotent
        |
 "Publish the poll on the devices": link + QR on table phones and in the QR tab
        |
 citizens scan and vote on their own phones  ------------------------------->   votes, optional new statements
        |                                                                              |
        |                                                                       opinion groups, consensus
        |                                                                              |
        |                                                                       Polis report (web page)
        |
 (not built) results pulled back: GET /api/v3/citizens/results/{id}, job PULL_POLIS
        |
 one unified report in Citizens (PDF), including the Polis results
```

The last two steps are not built; see [Roadmap](roadmap.md).

## Who does what

1. The organizer and facilitators plan and run the assembly and record the tables in Citizens; see
   [Running an assembly](../organizers/index.md).
2. The organizer transcribes, analyzes, reviews and approves the findings; see [After the assembly](../organizers/after.md) and
   [Transcription and analysis](../architecture/transcription-analysis.md).
3. The organizer generates, reviews, orders and approves the statements in Results, Polis seeds; see
   [Polis consultation](../organizers/polis.md) and [Seeds formats](../reference/seeds-formats.md).
4. The Polis operator issues an API key on the Polis host with `create-apikey.sh`; see [Connecting an installation](setup.md).
5. The Citizens administrator enters the instance URL and key in Settings, AI, Polis and tests the connection; see the
   [Settings reference](../admin/settings.md#polis).
6. The organizer sends the statements (job `PUSH_POLIS`); see [Contract](contract.md) and [Jobs](../architecture/jobs.md).
7. The Polis owner moderates, tunes and, if wanted, lists the conversation; see [Running a conversation](../polis/organizers.md).
8. The organizer publishes the poll on the devices; see [Polis consultation](../organizers/polis.md#put-the-poll-on-the-devices).
9. The public votes on the Polis voting page, and the organizer and the public read the Polis report; see
   [Polis concepts](../polis/concepts.md#opinion-groups-and-consensus).

Putting the results into the Citizens report is not built; see [Roadmap](roadmap.md).

## How the bridge behaves

Polis voting is open to anyone with the link. There is no login and no participant code. Votes are never linked to a table: Polis
knows nothing about tables or about the assembly beyond its name, and participants are anonymous cookies. There is no Polis-side
PDF, and participant codes (the xid whitelist) are not supported.

Publishing the poll on the devices shows the link and a QR code on the table phones and in the QR tab, and withdrawing takes it
off. The Polis conversation itself stays open until its moderator closes it.

## Pages in this section

| Page | Contents |
|---|---|
| [Connecting an installation](setup.md) | Key, Settings, test, egress, rotation, troubleshooting |
| [Contract](contract.md) | The calls, bodies, limits, idempotency, what each side stores |
| [Privacy across the bridge](privacy.md) | What crosses, what does not, who is responsible |
| [Roadmap and open questions](roadmap.md) | Results back into the report, participant codes, open items |
