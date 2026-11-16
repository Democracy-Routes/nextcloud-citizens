# Recovery and import

This page shows how to bring a session in from another server and how to rescue a table whose
audio or transcript failed. The routes behind these buttons are listed in the
[API reference](../reference/api/uploads.md).

## Bring a session in from another server

Use this when you have a session export (`export.zip`, from the Files tab of an assembly on another
Citizens server, format version 1 or 2) and want the assembly on this server.

1. On the Home page, press **Import a session**.
2. Choose the `export.zip` file. Large files are sent in pieces; you see progress, and the file is
   checked at the end to make sure it arrived whole.
3. Optional: give the assembly a new name. Otherwise it keeps its old one.
4. Optional: if a replacement phone joined under a new table number, add a table merge: "put the
   recordings of table 7 into table 3". The analysis then treats both recordings as one discussion.
5. Press import. When it finishes you get a short result: what was created, whether the analysis was
   queued, and what was skipped. Press **Open the assembly**.

The import creates a new, closed assembly with a new id, with its rounds, tables, participants (labels,
names, emails, notes, registered table), recordings, transcripts and any audio files the archive
carries. A recording with neither transcript nor audio is kept as a record of the table that failed.

Findings, summaries and the report are not copied. The analysis runs again
here, with this server's provider and the assembly's own instructions, and you review the findings as
you would after a live session. If no analysis provider is configured, the result says the analysis was
not queued; add a key in Settings and use the analysis controls on the assembly.

If the import is refused, the message says why (for example the hash did not match, or the file is not
a session export). Nothing is created in that case.

## When a table's audio or transcript failed: attach files

Sometimes a table's own pipeline fails but you still have the material: the audio was repaired by hand,
or the conversation was transcribed somewhere else. Open the assembly, go to the **Files** tab and find
the table's row.

| Action | Available when the table is | What happens |
|---|---|---|
| **Attach audio...** | Audio unusable, Upload incomplete, Transcription failed | The server checks the file is audio (with ffprobe), stores it as the table's audio and queues transcription with the configured provider. With none configured, transcribe later from the same row |
| **Attach transcript...** | the same states, and also Audio ready, Transcribed, Ready for review, Reviewed, Analysis failed | A JSON file in the shape of `transcripts/<id>.json` from a session export: provider, model, language and segments (speaker, start, end, text). The table goes to Transcribed and its analysis is queued |
| **Replace transcript...** | the table already has a transcript | Same file, but you confirm first because the old transcript is removed. Findings whose quotes pointed at the old text are flagged |

Attach audio when you have it, because the transcript can then be checked against the recording. Attach
a transcript when you only have text. The app records provider and model exactly as given in the file, so
put the truth there; it cannot verify them.

## How uploads work

Whole files go up in parts because the proxy caps a request body at a few megabytes: an upload is opened,
sent in 5 MB parts, completed with a SHA-256 check of the whole file, and then used by the import or the
attach action. Uploads belong to the organizer who opened them. The parts live in the server's temp
storage until the import completes; unfinished uploads are discarded by the housekeeping sweep after 24
hours.

## Privacy

An imported archive carries transcripts and participant data. Once imported they are this server's data,
under the same retention and deletion rules as a live session. Imports and attachments are audit-logged
as `session_imported`, `transcript_attached` and `audio_attached`. See
[Privacy and security](../privacy/index.md#imported-archives-and-attached-files).
