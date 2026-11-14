# Facilitator guide

This page is for the person carrying the facilitator's own phone at one table. It is not for the
phone that is actually recording, and not for the organizer running the whole event from a laptop
(see [On the day](on-the-day.md)). Your phone follows your table: who is there, whether they have
consented, how the recorder phones are doing, and a quiet assistant that occasionally has
something worth saying.

## Joining

On the table's own phone (the one recording, or any phone already joined to the table), tap
**Add facilitator**. It shows a QR code and a link; scan or open it on your own phone and it joins
you to that table. The session lasts twelve hours and survives a reload: if your phone sleeps or
you close the tab, reopening the app brings you back to the same table. The code does not expire
after one use, so a second person can pick up facilitation too.

This is a separate phone from the recorder. If you only have one phone, see
[Use this phone as a second recorder](#use-this-phone-as-a-second-recorder) below, which drops
this phone out of the facilitator role.

## What you see

Your screen follows one table and refreshes every few seconds.

* **The question and the goal**, and a clock if the session has a planned time ("X min left",
  "Last minute", "Over by X min"). A Record-now table has no clock.
* **Who is at the table:** names, who has registered, who has consented.
* **The recorder phones' status:** if the table has more than one, which one is feeding the server.
* **A recorder alert** when one needs you: "Recorder A has sent no audio for N s - go and look at
  that phone". It appears about thirty seconds after a recording phone stops sending audio.
  There is nothing to press.
* **The AI assistant's card**, if the organizer turned it on.
* **Messages from the organizer**, if they sent one from the Live tab.
* **The speaking balance**, when the transcription engine can tell voices apart: who has talked
  most in the last few minutes, no names attached.

## The AI assistant

An optional quiet voice beside your table, off unless an administrator or the organizer turned it
on. Once a minute, if there is something worth saying (time running out, a long silence, one voice
dominating), it offers one short sentence. It reaches your phone first, as a card with two
buttons: **Dismiss** (nobody at the table sees it) or **Send to the table** (it appears on the
recorder's screen as a prompt, with a chime). Afterwards, say whether it was helpful; three "not
helpful" votes turn it off at your table for the rest of that session.

The assistant's own card says "AI assistant", so it is never confused with you: "facilitator" on
screen always means the person at the table. It reads only your table's own live captions, with
every known participant's name already replaced by a placeholder, and never sees another table.
If no facilitator phone is connected, the advice goes straight to the recorder's screen.

## Writing to the table

Your own prompt box takes up to 300 characters, for anything you want to say without interrupting
out loud: a reminder of the question, a nudge to move on, a note for whoever takes notes. **Send to
the table** shows it on the recorder's screen, labelled "From the facilitator", with a chime.

## Raising your hand

**Need help** asks what kind (technical problem, call the organizer, question about the process)
and your phone then says "Organizer notified". It stays on the organizer's Live tab against your
table until they acknowledge it, at which point your phone says "The organizer has seen it". It is
not offered on a Record-now table, which has no organizer to call.

## Consent from this phone

**Register for consent** opens the same registration screen the table's phone offers: read the
notice, enter a name (optionally an email) and tick the two consent boxes. It is useful when the
table phone is busy recording and someone new sits down. The record is exactly the same as if it
were made on the table's own phone. See [Consent and the notice](../privacy/consent.md).

## Use this phone as a second recorder

**Use this phone as a second recorder** hands this phone to the ordinary recorder app, joined to the
same table as another recorder. It drops the facilitator role from this phone; if the table still
needs a facilitator, someone scans the **Add facilitator** code again on a different phone.

## When a recorder phone goes quiet

Nothing, by design. A dark screen, a closed browser, a phone left in a bag: the server notices
within about thirty seconds (the alert above) and, if nobody has fixed it, finishes that recording
itself after five minutes with whatever audio arrived. It is transcribed and analysed like any other
table. If that phone comes back and keeps recording, what it sends next is not refused: it is kept,
transcribed and folded back into the table's findings.

## Finishing a recording

That is not done from here. **Finish recording** is a button on the organizer's Live tab; there is no
such control on the facilitator's phone. If your table is done early and its recorder is still going,
tell the organizer (or use **Need help**), or wait for whoever holds that phone to press Finish.

## Leaving

**Leave this table** ends your own session on this phone. It does not touch the recording, the
table's consent records, or anything anyone else at the table is doing.

## Privacy of the facilitator phone

The server keeps only a hashed bearer with the table number and timestamps: no name, no audio, no
captions. The facilitator's page reads the same roster (names only) and messages the table's phones
read; what it writes (a prompt, a hand raised) is audited under the session id. See
[Privacy and security](../privacy/index.md).
