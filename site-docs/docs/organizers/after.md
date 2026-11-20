# After the assembly

This page walks through closing an assembly, reviewing and publishing the report, exporting the
data and clearing the phones. Do the steps in order; only the last one, clearing the phones,
deletes anything on devices.

## 1. Close and wait for processing

Press **Close ... & create the final report**. Closing freezes the version participants read.
Downloads become available once the assembly or session is closed. You can reopen it later,
except after zero retention has run. Wait for processing: transcription and analysis run as
background jobs (see [Jobs and background work](../architecture/jobs.md)).

## 2. Review the findings

Open the **Analysis** tab. AI findings are drafts until you approve them, and the report states
that a person approved its findings. (A Record now session is the exception: its findings are
approved automatically when it closes and its report says that no person reviewed them; see
[Concepts](concepts.md#record-now).) For each finding you can approve, edit or reject; filters
for review status and finding type help, and **Approve N draft(s)** approves everything still
waiting in the round (rejected findings are left alone, and anything approved can still be
edited or rejected later). Each finding shows its evidence: speaker, timestamp and exact words.

Re-running the analysis replaces reviewed findings. A run replaces the whole generation of
findings it supersedes, approved and edited ones included, and the dialog says so before you
confirm. A re-run that returns no findings for a table that had some is refused, and the
previous findings are kept.

Cross-table findings are regenerated every time another table finishes its analysis, so review
those only after the last table is in. A failed synthesis or cross-table analysis is shown in
red on the Report tab with its reason, and in the `failures` block of
`GET /api/v1/assemblies/{id}/progress`; fix the cause (a rejected key, a model that refused) and
re-run it.

If a transcript is wrong, **Re-transcribe** on the table's row in the Files tab transcribes
again from the stored audio and re-runs the analysis. Quotes inside existing findings that
referred to the old text are marked as removed.

## 3. Reports

The Report tab builds the final report from the approved findings and the AI summaries, which
are labeled as AI-generated. Formats and what each contains are in
[Report formats](../reference/reports.md): a branded PDF (executive summary, points of consensus
and divergence, participation coverage, one page per table in the table detail), Markdown and
JSON. If anyone seated at a table declined the quotations box, the report prints no verbatim
quotation from that table and says so under it.

## 4. Publish to the devices

**Publish report to tables** lets every recording phone view the report and download the PDF.
Only approved findings and AI summaries are included; unreviewed drafts stay private.
**Unpublish** removes access at once; you can publish again at any time. Participants who
registered on their own phone see their registration, their consent and, once published, the
report. Participants can also validate their own table's summary once the report is published.

Reopening an assembly leaves the frozen published copy alone on purpose. After approving more
findings or renaming the assembly, press **Update the published version** on the Report tab to
push the current content.

## 5. Export before you delete anything

Each assembly has a Files tab listing every table's audio with size and duration. You can
download one table's audio or all of it, and export the whole session as a portable archive
(metadata, audio, transcripts and report). That archive can be imported on another server; see
[Recovery and import](recovery-import.md). Open what you downloaded: a download starting is not
proof that a file saved or plays.

## 6. Clear the phones

Every phone keeps a copy of its table's audio, which matters most when participants used their
own devices. Closing an assembly asks the phones to clear their copy automatically (default on,
switchable per assembly under *Assembly details* on the Overview tab). **Clear audio from the
table phones** on the Files tab asks again. It reaches only phones whose recorder page is still
open, reports how many confirmed, and is coverage, not a guarantee. A phone deletes only audio
the server has already confirmed, so the request cannot destroy a last copy.

## Retention

Settings, Organisation, *Retention* sets how many days after an assembly is closed its audio
is deleted; `0` keeps it indefinitely, and each assembly can override the instance default.
Deletion runs from a periodic sweep and is audit-logged. It removes audio only:
transcripts, findings and reports are the record of the assembly. Deleting those is manual, from
the Files tab.

Zero retention is a third choice on the same control and in the creation wizard: *Zero
retention - keep only the report*. Once the assembly is closed and every transcription and
analysis has finished, the audio, every transcript and the live-caption files are deleted
outright, and a PDF of the frozen report is kept; from then on `report.pdf` serves that file.

!!! danger "Zero retention cannot be undone"
    The assembly can never be reopened (it answers `ZERO_RETENTION_APPLIED`), and its language
    can no longer be changed because there is no audio left to transcribe again. Choose it only
    when the report really is the only thing worth keeping, such as a throwaway rehearsal or an
    organization that does not want to hold recorded speech any longer than it has to.

See [Privacy and security](../privacy/index.md) for the full retention rules.

## Changing things afterwards

* Rename: click the pencil beside the name in its header; Enter saves, Escape cancels. The
  name inside a frozen report changes only after **Update the published version**.
* Change the language: the Overview tab's language select stays open. Once a table has
  recorded you are asked to confirm, because every recording with audio is transcribed again and
  the findings and report follow. It is refused while a session is being recorded and, after zero
  retention, for good.
* Delete: deleting an assembly removes its recordings, transcripts, live captions, findings,
  reports, exports and the phones' diagnostic logs, and purges its storage directory.
