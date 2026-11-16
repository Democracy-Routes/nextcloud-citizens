# First assembly in 15 minutes

This walk-through takes you from a fresh install to a published report, using a throwaway
session and one or two phones. It rehearses the flow, not the venue; for a real event also
follow [Before the day](../organizers/before-the-day.md).

!!! warning "Providers cost money"
    If you use Deepgram, Mistral or another hosted engine, this walk-through sends audio
    to it. Use a self-hosted engine (Vosk or a Whisper server) to keep a rehearsal free
    and local. See [Providers and egress](../admin/providers-egress.md).

## Before you start

* The app is running and you can open **Citizens** (the Nextcloud top menu, or your
  standalone address).
* Settings has a speech-to-text engine and an analysis endpoint, and you used the *Test*
  buttons. Without them the walk-through stops after recording.
* You have two phones with a current browser, on the same network as the server's HTTPS
  address.

## 1. Create a session

On **Home** the three actions are **Record now**, **Start a Session** and **Create an
Assembly**. For a first run, choose **Start a Session**. A Session is one question discussed
at one or more tables; an Assembly is an optional container around several Sessions. Enter
the question, the number of tables and, optionally, a planned time and an objective. See
[Concepts](../organizers/concepts.md).

## 2. Print the QR sheet

Open the **QR codes** tab. Citizens generates one recording code per table. Print the sheet,
or the event kit (a card per table with its color and code), and place one code on each
physical table. For the walk-through you can leave the codes on screen.

The address on the code comes from your public URL: `overwrite.cli.url` in Nextcloud mode,
`CITIZENS_PUBLIC_URL` in standalone mode. Check it before printing.

## 3. Join the phones

On each phone, scan one table's code. The phone opens the recorder page. It shows the
information screen, which names the transcription engine, how long audio is kept and how
speakers are labeled, and asks each person to register and consent. Consent is explained in
[Consent and the notice](../privacy/consent.md). In live (orchestrated) mode the table then
taps **Ready** and waits on an armed screen.

## 4. Record

On the **Live** tab, press start for the round. Armed phones begin recording together. Watch
each table: connectivity, chunks uploaded, and battery where the browser reports it. Let
people talk for a couple of minutes.

## 5. End the round

Press end on the Live tab, or let the Live tab count up past the planned time and offer to
end it. Phones show a 15-second cancellable "finishing" countdown, then finish and
synchronize. Wait until every table reaches the green `AUDIO_READY` state on the server, not
only "synchronized" on the phone. Transcription and analysis follow automatically.

## 6. Review

Open the **Analysis** tab. Every finding is an AI draft with the transcript passages that
support it. Approve, edit or reject each one; **Approve N draft(s)** approves everything
still waiting in the round. Review the cross-table findings after the last table is in,
because they are regenerated every time a table finishes. Review cannot be skipped.

## 7. Close and publish

Press **Close ... & create the final report**. The downloads (the PDF, Markdown and audio)
become available once the session is closed. On the **Report** tab, **Publish report to
tables** lets each recording phone view the report and download the PDF. Only approved
findings and AI summaries are included. See [After the assembly](../organizers/after.md).

## 8. Clean up

Delete the throwaway session. Deleting an assembly or session removes its audio, transcripts,
live captions, findings, reports and exports. See
[Privacy and security](../privacy/index.md#deleting-everything-for-one-assembly).
