# Report formats

A report is built from the approved findings and the AI summaries of an assembly. Drafts are excluded unless explicitly requested.

## Formats and routes

| Format | Route | Notes |
|---|---|---|
| JSON | `GET /api/v1/assemblies/{id}/report` | Available at any time (a preview before closing). Query `include_drafts=true` includes unreviewed drafts |
| Markdown | `GET /api/v1/assemblies/{id}/report.md` | Requires the assembly to be closed. `text/markdown; charset=utf-8` |
| PDF | `GET /api/v1/assemblies/{id}/report.pdf` | Requires the assembly to be closed. For a zero-retention assembly this serves the PDF stored before the transcripts were deleted |

Close the assembly first (`POST /api/v1/assemblies/{id}/close`) to create the final report and enable the downloads. `POST .../report/refresh` rebuilds a closed
assembly's frozen report, `POST .../report/publish` and `DELETE .../report/publish` publish it to or withdraw it from the table phones, and
`GET .../progress` reports processing state including the `failures` block. These are specified in the [API reference](api/assemblies.md).

## Content

The JSON document has an `assembly` header (name, description, language, kind, status, recording mode, participants and expected participants) and a list of
rounds. Each round carries:

* its position, title, heading, question, objective and status;
* an AI summary and the number of recordings;
* **cross-table** findings;
* a speaking comparison across tables;
* per-table sections: table number, AI summary, speaking balance, the table's findings, whether quotations are withheld, and participant validations.

Each finding has an id, type and type label, title, summary, support level, status, whether it is a draft, its table number, the number of tables that mentioned it, and
its evidence (speaker, time and text) unless quotations are withheld or the evidence was removed.

The PDF is a branded document with the organisation's name and logo (from Settings), an executive summary, points of consensus and divergence, and participation coverage. Each
table of a round starts on its own page with a banner and a "Table N" footer marker. Plenary reports are unchanged. Reports still print "Round N" headings.

## The methodology note

Every format carries a methodology note built from the facts of the assembly:

* a standing paragraph: AI assisted transcription and analysis, discussion summaries are AI-generated neutral descriptions, and "Mentioned at N tables" counts tables that raised a topic and
  is not a measure of participant support;
* "Findings were reviewed by a human organizer", only when at least one finding was approved;
* a note when quotations are withheld because a participant seated at a table declined being quoted;
* "Speech-to-text: ..." naming the engines, and "Analysis: ..." naming the models that wrote the findings;
* a note when the transcript is built from live captions only;
* a note when a table's device was replaced, so the report reads as one discussion;
* how many people registered at the tables and how many consented;
* how many participants answered the validation of published summaries.

## The "Powered by" line

Every report ends with "Powered by democracyroutes.com": on every page of the PDF in its footer, and as the last line of the Markdown. It is not a setting.

## Languages

Reports are written in the assembly's language: English, Italian, German, French or Spanish. The strings are in `citizens/services/report_text.py`.

## Frozen and published copies

Closing freezes the version participants read. **Publish report to tables** makes it viewable and downloadable (PDF) on the recording phones; only approved findings and AI summaries are
included. Reopening leaves the frozen copy alone; **Update the published version** pushes the current content.
