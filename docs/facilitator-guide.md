<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->

# Facilitator guide

For the person carrying the facilitator's own phone at one table — not the
phone that is actually recording, and not the organizer running the whole
event from a laptop (that is [administration.md](administration.md) and its
Live tab). Your phone follows your table: who's there, whether they've
consented, how the recorder phones are doing, and a quiet assistant that
occasionally has something worth saying.

## Joining

On the table's own phone (the one recording, or any phone already joined to
the table), tap **Add facilitator**. It shows a QR code and a link; scan or
open it on your own phone and it joins you to that table. The session lasts
twelve hours and survives a reload — if your phone sleeps or you close the
tab, reopening the app brings you straight back to the same table, no need
to re-scan. The code itself doesn't expire after one use, so a second person
can pick up facilitation too, or hand it to someone else mid-session.

This is a separate phone from the recorder. If you only have one phone and
the table needs you to record as well, see **Use this phone as a second
recorder** below — but note it drops this phone out of the facilitator role.

## What you see

Your screen follows one table, refreshing every few seconds:

* **The question and the goal** — what this session is about and, when the
  organizer set one, what it should produce — plus a clock, if the session
  has a planned time ("X min left", "Last minute", "Over by X min"). A
  Record-now table has no planned time, so there is no clock: the table
  decides when it is done.
* **Who's at the table** — names, who has registered, who has consented.
* **The recorder phones' status** — if the table has more than one, which
  one is actually feeding the server right now.
* **A recorder alert**, when one needs you: "Recorder A has sent no audio
  for N s — go and look at that phone: is the recorder still open and in
  front?" It appears about thirty seconds after a recording phone stops
  sending audio — screen off, browser closed, out of range — so you can
  check on it before it matters. **There is nothing to press here**; see
  "When a recorder phone goes quiet" below for what happens if nobody does.
* **The AI assistant's card**, if the organizer turned it on — see below.
* **Messages from the organizer**, if they sent one from the Live tab.
* **The speaking balance**, when the transcription engine can tell voices
  apart: who has talked the most in the last few minutes, no names attached.

## The AI assistant

An optional quiet voice beside your table, off unless an administrator or
the organizer turned it on. Once a minute, if there is something worth
saying — time running out, a long silence, one voice dominating — it offers
one short sentence. It reaches your phone first, as a card with two
buttons: **Dismiss** (nobody at the table sees it) or **Send to the table**
(it appears on the recorder's screen as a prompt, with a chime). Afterwards,
say whether it was helpful or not — three "not helpful" votes turn it off
at your table for the rest of that session; the next session is a fresh
chance. It is the software's voice, never a person's: "facilitator" on
screen always means you, the person at the table, and the assistant's own
card says "AI assistant" so the two are never confused. It reads only your
table's own live captions, with every known participant's name already
replaced by a placeholder — it never sees another table.

If no facilitator phone is connected to a table, the same advice goes
straight to the recorder's screen instead. A table nobody is facilitating is
never left without it, but a facilitator who is there gets to decide first.

## Writing to the table

Below the assistant's card is your own prompt box — up to 300 characters —
for anything you want to say to the table without interrupting it out loud:
a reminder of the question, a nudge to move on, a note for whoever is taking
notes. **Send to the table** and it appears on the recorder's screen,
labelled "From the facilitator", with a chime.

## Raising your hand

If your table needs the organizer — a technical problem, a question about
how the process works, or you just need them to come over — use **Need
help**. It asks what kind (technical problem / call the organizer /
question about the process) and your phone then says "Organizer notified".
It stays on the organizer's Live tab against your table until they
acknowledge it, at which point your phone says "The organizer has seen it".
This is not offered on a standalone Record-now table, which has no
organizer to call.

## Consent from this phone

**Register for consent** opens the same registration screen the table's own
phone offers: read the notice, enter a name (optionally an email), and the
two consent boxes. Useful when the table phone is busy recording and
someone new sits down, or a latecomer needs registering without disturbing
it. What is recorded is exactly the same consent record as if it had been
done on the table's own phone — see [privacy.md](privacy.md) and
[consent-form.md](consent-form.md).

## Use this phone as a second recorder

If the table needs another recording phone — the first one is struggling,
or you want a backup from the start — **Use this phone as a second
recorder** hands this phone to the ordinary recorder app, joined to the same
table as another recorder. This drops the facilitator role from this phone:
it becomes a recording phone, not a follower of the table. If the table
still needs a facilitator after that, have someone scan the **Add
facilitator** code again on a different phone.

## When a recorder phone goes quiet

Nothing — that is the point. A screen that has gone dark, a browser that
has been closed, a phone left in a bag: the server notices within about
thirty seconds (the alert above) and, if nobody has fixed it, finishes that
recording itself after five minutes with whatever audio arrived. It is
transcribed and analysed like any other table, and the alert simply clears
once there is no longer a live recording to warn about. If that phone comes
back and keeps recording — someone picks it up again, unaware anything
happened — what it sends next is not refused: it is kept, transcribed, and
folded back into the table's findings. You do not need to notice, chase
anyone, or press anything; it is one of the few things at a table that
genuinely fixes itself.

## Finishing a recording

That is not done from here. **Finish recording**, for one table's recorder,
is a button on the organizer's Live tab, not on the facilitator's phone —
there is no such control on this phone at all. If your table is done early
and its recorder is still going, tell the organizer (or use **Need help** if
you cannot reach them), or wait for whoever is holding that phone to press
Finish on it themselves.

## Leaving

**Leave this table** ends your own session on this phone. It does not touch
the recording, the table's consent records, or anything anyone else at the
table is doing — it only stops this phone from following the table.
