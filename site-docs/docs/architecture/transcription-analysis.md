# Transcription and analysis

## Providers

Transcription adapters live in `citizens/providers/transcription/` (`deepgram.py`, `mistral.py`, `whisper.py`,
`vosk.py`); the analysis adapter is OpenAI-compatible (`citizens/providers/analysis/openai_compat.py`). Live caption and
final (batch) models are configured separately per provider; see the [Settings reference](../admin/settings.md). Server-wide
concurrency caps per provider and kind stop an uncapped plenary room from saturating a self-hosted engine or a hosted
provider's rate limit: over-cap phones keep recording and their captions wait for a slot. A final transcription that is
merely waiting for a slot is retried every 60 seconds without costing an attempt.

An analysis reply whose content is a list of parts (Mistral Large since 2026-11) is read part by part, and thinking parts
are ignored.

## Live captions and final transcripts

The two switches are independent (the combinations are in the Settings reference). With final transcription off, a finished
caption session's lines are written to `live_captions/` and the `TRANSCRIBE_FROM_LIVE` job turns them into a real `Transcript`
through the same `store_transcript()` the provider adapters use, so analysis, evidence citations and reports need no special
case. `transcripts.source` (`final` or `live`, migration 0014) records which happened and drives a line in the report's
methodology note.

A caption session keeps every line it produced, not just the window it displays: `status()` returns the last `MAX_LINES` for
the phone while `session.lines` holds the whole round. Persisting appends to any file already there, so a session that dies and
reconnects does not erase what preceded it.

## From transcript to findings

The analysis runs per table, then per round across tables:

1. **Per table (`ANALYZE_TABLE`).** The model receives the table's transcript (with listed names replaced; see
   [Pseudonyms and names](../privacy/pseudonyms.md)) and returns JSON validated against a Pydantic schema
   (`citizens/domain/analysis_schemas.py`). Invalid output is never stored: the provider retries with a correction prompt and
   anything that still fails validation is rejected.
2. **Per round (`ANALYZE_ROUND`).** Findings from the tables are clustered into cross-table findings with
   `source_finding_ids`. Clustering re-runs every time another table's analysis lands; draft round findings are replaced,
   reviewed ones kept in independent mode.
3. **Across sessions (`ANALYZE_ASSEMBLY`).** A narrative synthesis of how the discussion developed: a narrative, its stages, and
   what was carried forward.

A **finding** has a type (`proposal`, `agreement`, `disagreement`, `concern`, `question`, `minority_position`, `new_idea`), a
title (3 to 300 characters), a summary, an optional support level (`strong`, `mixed`, `weak`, `unclear`) and between 1 and 20
evidence segment ids. Every analysed table also stores a mandatory neutral summary of two to four sentences in the assembly's
language, even when there are no substantive findings, and rounds store a cross-table summary. Summaries render in the Analysis
tab and in reports labelled as AI-generated.

### Evidence

Evidence is the guard against invention. A finding must cite at least one transcript segment, and a finding with no evidence is
discarded automatically. A finding cites at most six quotations in the report. Each evidence link carries the speaker label, start
and end time and the exact text. Round findings borrow evidence from the table findings they cluster. When a transcript is
replaced or re-transcribed, quotes that referred to the old text are marked removed rather than left pointing at nothing, and
findings whose evidence pointed at old segments are flagged.

### Limits

A table transcript longer than roughly 180,000 characters is cut for the analysis prompt: the start is kept, the rest is noted as
cut, and the log says how much was left out. For plenary rooms, `merge_plenary_segments` aligns and de-duplicates the devices'
transcripts first (see [Recording pipeline](recording-pipeline.md)). An assembly's language chooses the language of the prompts and
output (`LANGUAGE_NAMES` in `citizens/services/analysis.py`); Record now detects it once from the first transcript.

### Review

Findings are `DRAFT` until an organizer sets `APPROVED`, `EDITED_AND_APPROVED` or `REJECTED`; only the two approved statuses count
as reviewed (`APPROVED_STATUSES`). A run that supersedes a generation of findings replaces it entirely. A re-run that returns no
findings for a table that had some is refused and the previous findings are kept.

## The report build

`build_report()` in `citizens/services/report.py` assembles one JSON document: the assembly header (name, description, language,
recording mode, participants and expected participants), then each round with its question, objective, summary, cross-table
findings, speaking comparison and per-table sections (summary, speaking balance, findings, `quotations_withheld`, participant
validations). Drafts are excluded unless `include_drafts` is set. Markdown and PDF are rendered from that document
(`services/report.py`, `services/report_pdf.py`, with strings in `services/report_text.py` for English, Italian, German, French and
Spanish). The methodology note is built from the facts of the assembly: the standing AI-use paragraph, whether a human reviewed
findings, withheld quotations, the speech-to-text engines (`transcripts.provider` and `model`), the analysis models
(`findings.ai_model`), live-caption provenance, device replacement, how many consents were recorded at the tables and how many
participants answered the validation. See [Report formats](../reference/reports.md).

The PDF gives each table of a round its own page with a banner and a "Table N" footer marker. The brand line
(`report_text.POWERED_BY`) is on every page's footer and ends the Markdown. For zero-retention assemblies a PDF of the frozen
report is stored before the transcripts go and served thereafter.

## Polis seeds pipeline

`services/seed_pipeline.py` runs the three passes (ground, draft, critique) described in
[Polis consultation](../organizers/polis.md), as the `SEED_STATEMENTS` job; `PUSH_POLIS` sends the approved statements. Provenance
(finding, claim, excerpt, scores) is stored with each seed (migration 0042).
