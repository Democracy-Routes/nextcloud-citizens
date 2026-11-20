# Concepts

This page defines the terms the interface and the reports use, so you can read the Live tab and
the findings without guessing.

## Session and Assembly

An Assembly is an optional, organized event. A Session is one question discussed at one or
more tables, and it is the unit you start from, on its own or inside an Assembly. A Table is
one discussion within a Session, numbered and colored. A Recorder is a phone recording a
Table; a Table has one or more.

Home opens on two actions: **Record now** and **Create a session**, with *Import a session* as a
small link underneath. The session wizard has **Add another session**: with two or more sessions
it asks for a name and the event options and creates a **multi-session** event (the interface's
name for what the code calls an assembly). A Session can also grow into a multi-session event
later without losing its tables, codes or report. An event's tabs are grouped as Plan, Run and
Results under a timeline of its sessions.

The schema, the routes and parts of the code still spell a Session as a Round (`rounds`,
`round_id`, `/rounds/{id}`). Newer product and API surfaces say Session (`POST /sessions`,
`GET /sessions`). A `session_id` in a Session payload is a round id, and every `/rounds/{id}`
route accepts it. Reports still print "Round N" headings. A standalone Session is a Round
inside a container Assembly of kind `session` that the interface never presents as an
assembly.

## Rounds

A round is one discussion slot with a `question` and an optional `objective` (for example
"produce three concrete proposals") that reaches the phone, the analysis prompts and the
reports. The planned time is the round's `duration_minutes`.

## Tables

A table is the physical table the room knows. Its number is the same in every round and
is printed on the QR sheet and carried by every phone and recording. Beside it a color
(one of six, chosen by number and repeating after six) is a cue for a room looking for "the
blue table"; correctness never depends on it. Tables can be added mid-event: the next
number is added to every round at once with its own printed code, without changing the
codes already on the wall.

## Recorders

A table can have more than one recorder phone. The table's own printed code is slot 1 (a
replacement that rescans it takes the same role); an added recorder gets the next slot.
Recorders in different slots record side by side. Only one recorder per table feeds the live
captions; the others store audio but are not handed to the caption engine, and the Live tab
shows which recorder carries them. A *facilitator* phone is a different thing: it follows a
table but never records. See the [facilitator guide](facilitator.md).

## Participants

Participants register one at a time, on the table's phone or on their own phone through a
registration code the table shows, giving a name (required), an email (optional) and two
consent boxes. Participants can also be pseudonymous (`P001`...). Names and emails are
optional everywhere in the data model, except the name in the consent registration. See
[Consent and the notice](../privacy/consent.md).

## Recording modes

### Live (orchestrated)

This is the default. Tables tap READY once and sit on an armed screen. You start and end each
round, and every armed table records at the same time. The server rejects a recording start
for a round that is not active.

### Independent

Each table works through the same questions on its own schedule, even days apart. The Start
and End controls are hidden on the Live tab, and cross-table clustering re-runs incrementally
as each table's analysis arrives.

### Plenary

One shared recorder: the whole room is a single discussion captured by many phones at once,
and the "one recording per table" guard is lifted. The server aligns the devices' transcripts
on its own clock and drops near-duplicate utterances.

### Record now

One phone, one table, no set-up and no planned time. It records until the table is done. The
Live tab and the phone show no countdown and never finish it automatically. Its done screen
offers **Record another session**.

Record now is the **self-organized** mode (0.9). When no phone at the session has recorded for
the configured minutes (Settings → Organisation, default 10; a session with a single phone closes
a minute after it finished), the server closes it, approves every finding once the analysis has
run, freezes and publishes the report, and the phone opens it with its PDF. With Polis
configured, the statements are then generated, approved and sent, and the voting QR appears on
the phones. Phones that joined by code only stop their own recording; only the organizer account
closes the session for everyone, and closing from the app first asks every phone still recording
to finish. The report says that its findings were selected by the AI and not reviewed by a
person. A Session is the organized-event mode and keeps human review.

## Findings and review

The analysis produces findings for each table and for the round across tables. A finding
has a type, a title, a summary, a support level and evidence: the transcript segments it
rests on. Status is `DRAFT`, `APPROVED`, `EDITED_AND_APPROVED` or `REJECTED`; only the two
approved statuses count as reviewed. See [Transcription and analysis](../architecture/transcription-analysis.md).
