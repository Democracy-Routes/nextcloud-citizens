# Citizens + Polis

Citizens records and analyses an assembly of a few dozen people at tables. Polis lets a much larger public vote on short
statements and shows where they agree. The bridge turns the first into the input of the second: the findings an assembly approves
become the **seed statements** of a Polis conversation that anyone with the link can vote on, including the people in the room, on
their own phones.

The two are separate programs, in separate repositories, run separately. The bridge is a small, one-directional contract:
**Citizens calls Polis**; Polis never calls Citizens, and Citizens exposes no API to it.

## The flow, end to end

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
 (roadmap) results pulled back: GET /api/v3/citizens/results/{id}, job PULL_POLIS
        |
 one unified report in Citizens (PDF), including the Polis results
```

The last two steps are **not built**; see [Roadmap](roadmap.md).

## Who does what

| Step | Who | Where | Documented in |
|---|---|---|---|
| Plan and run the assembly, record the tables | Organizer, facilitators | Citizens | [Running an assembly](../organizers/index.md) |
| Transcribe, analyse, review and approve findings | Organizer | Citizens | [After the assembly](../organizers/after.md), [Transcription and analysis](../architecture/transcription-analysis.md) |
| Generate, review, order and approve the statements | Organizer | Citizens, Results, Polis seeds | [Polis consultation](../organizers/polis.md) (three passes, Why panel), [Seeds formats](../reference/seeds-formats.md) |
| Issue an API key for the installation | Polis operator | the Polis host, `create-apikey.sh` | [Connecting an installation](setup.md) |
| Enter the instance URL and key, test the connection | Citizens administrator | Citizens, Settings, AI, Polis | [Settings reference](../admin/settings.md#polis), [Connecting an installation](setup.md) |
| Send the statements | Organizer | Citizens (job `PUSH_POLIS`) | [Contract](contract.md), [Jobs](../architecture/jobs.md) |
| Moderate, tune and, if wanted, list the conversation | Polis owner | Polis organizer pages | [Running a conversation](../polis/organizers.md) |
| Publish the poll on the devices | Organizer | Citizens | [Polis consultation](../organizers/polis.md#put-the-poll-on-the-devices) |
| Vote | Citizens (the public) | Polis voting page | [Polis concepts](../polis/concepts.md) |
| Read the results | Organizer, public | Polis report | [Polis concepts](../polis/concepts.md#opinion-groups-and-consensus) |
| Results into the Citizens report | Organizer | Citizens | **Roadmap**: [Roadmap](roadmap.md) |

## Decisions that shape the bridge

These were taken on 2026-11-13 and are stated here because the rest of the pages depend on them.

* **Polis voting is open to anyone with the link.** There is no login and no participant code.
* **Votes are never linked to a table.** Polis knows nothing about tables or about the assembly beyond its name; participants are
  anonymous cookies.
* **One unified report.** Polis results are meant to go into the Citizens PDF in a later step; there is no Polis-side PDF.
* **Participant codes (the xid whitelist) are deferred.**
* **Publishing the poll on the devices** shows the link and a QR code on the table phones and in the QR tab; withdrawing takes it
  off. The Polis conversation itself stays open until its moderator closes it.

## Pages in this section

| Page | Contents |
|---|---|
| [Connecting an installation](setup.md) | Key, Settings, test, egress, rotation, troubleshooting |
| [Contract](contract.md) | The calls, bodies, limits, idempotency, what each side stores |
| [Privacy across the bridge](privacy.md) | What crosses, what does not, who is responsible |
| [Roadmap and open questions](roadmap.md) | Results back into the report, participant codes, open items |
