# Consent and the notice

Before a table can record, the recorder shows an information screen. This page explains what the screen
says, what is recorded when a person registers, and how consent acts behave. The paper form in
`docs/consent-form.md` is the fallback and is summarized in
[Before the day](../organizers/before-the-day.md).

## The information screen

The screen names the transcription engine, says whether that engine is an outside service, and states how
long audio is kept and that speakers are labeled only as "Speaker 1", "Speaker 2". The table confirms
before recording becomes available. The server generates the text from its live configuration, so it
matches what the app does, and shows it in the assembly's own language rather than the phone's. The screen
offers a decline as well as a confirmation, because a screen with only one button is not a consent step.

## The notice (version `2026-10.3`)

The screen is also where individual consent is recorded. The notice is versioned. The server renders it
from Settings (data controller and contact) and the live data-handling facts, in the assembly's language,
and hashes it exactly as shown; the text behind every hash is kept (`consent_notices`).

The notice opens with a paragraph making clear that recording is not a condition of taking part: a person
who does not consent can sit at a table that is not recorded. It names the transcription and analysis
providers selected in Settings and prints the organization data entered there (controller, address,
contact, data-protection contact, hosting, supervisory authority). Blank fields are left out, never shown
as placeholders.

The lawful basis documented in the paper form is explicit consent (GDPR Art. 6(1)(a) and Art. 9(2)(a)).

## Registration

Each person registers one at a time, on the table's phone or on their own phone through a registration code the
table shows (or a pre-registration link). The form asks for:

* a name (required);
* an email (optional);
* **two boxes**: a required one covering the audio recording of the discussion at the table, its transcription
  and AI-assisted analysis, and an optional one, ticked by default, covering short anonymous quotations in the
  assembly's report.

Leaving the required box unticked records a refusal; the optional box can be unticked on its own without
affecting the rest. The record (`participant_consents`: who, where, method, notice version and hash, the four
flags the two boxes cover, the server's timestamp) is stored as given. Registration is audited without name or
email.

## Consent acts are append-only

Nothing already recorded is overwritten, and the newest act for a person is the one that counts wherever
consent is checked. From the table phone's participants screen or the organizer's Participants tab, three
actions each add a new act:

| Action | Effect |
|---|---|
| **Changed their mind** (offered only after a refusal) | A new act with both boxes ticked again and the name unchanged |
| **Withdraws consent** | A new act with every flag false. What was already recorded is kept and keeps being processed, but the table cannot record this person again until they are moved or change their mind |
| **Moved to another table** | Takes the person off this table's roster for the sessions still to come and leaves their consent record untouched |

The consent register (CSV or PDF, from the Participants tab) lists every act ever recorded, one row per act. Each
act is audited (`consent_changed`, `participant_moved`, alongside `participant_registered`). A table's own phone
can act only on people seated at its own table; the organizer can act on anyone in the assembly. A closed
assembly accepts no further consent acts.

## When a table is blocked

An assembly set to **Consent at the table: required** (the default for an organized assembly) records a table only
once at least one person seated there has consented, **and only for as long as nobody seated there has refused or
withdrawn**. One refusal blocks the whole table; it is not outvoted by the rest. The seat that counts is the seat
of the current session's seating plan, falling back to the table the person registered at. To unblock a table in the
room, mark the refusing person **Moved to another table** (a table that is not recorded), on the table's phone
or from the Participants tab; the table can then record. The rule is enforced where recording starts,
not only on the phone. The Live tab shows the blocker as `PARTICIPANT_REFUSED`.

With *Optional* (the default for a spontaneous Session), the recorder shows the notice and offers registration
without blocking anything.

## Quotations

If anyone seated at a table declined the quotations box, the report prints no verbatim quotation from that table:
the table's findings stand on the analysis alone, the report states under that table that quotations from it are
withheld because a participant seated there did not consent to being quoted, and cross-table findings borrow no
quotation from that table either. The methodology note explains why. This withholds by table, not by the one person,
because voices are not separated in the recording.

## Rights

Erasing a participant from the Participants tab erases their consent record (cascade). The export carries every
record and every notice text, so a subject-access request can be answered from the archive. Withdrawal is handled
through the contact on the notice: there is no self-service withdrawal, and a withdrawal does not undo processing
already done. A person who registered on their own phone keeps a page showing their registration, their consent and,
once published, the report.

!!! warning "Not legal advice"
    The notice and the paper form are templates based on what the software does. Have counsel read them if the
    organizer is a public body, which may rely on another basis in law.
