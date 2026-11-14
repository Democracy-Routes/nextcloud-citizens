# Seeds export formats

The statements an organizer approves in Results, Polis seeds can be downloaded as CSV or JSON once every statement is approved or rejected and at least one is approved. Positions are
renumbered 1 to n over the exported statements. The files hold statement text only: no evidence, no transcript, no participant data, no table numbers and no Citizens ids. The only
identifier is the assembly **name** (and language); there is no assembly id or date.

See [Polis consultation](../organizers/polis.md) for the workflow.

## CSV

`<assembly>-statements.csv`: UTF-8, a header row, RFC 4180 quoting.

```text
position,statement
1,"Il comune dovrebbe pubblicare ogni anno il bilancio in forma leggibile."
2,"Le assemblee cittadine dovrebbero avere un seguito vincolante."
```

## JSON

`<assembly>-statements.json`, schema `citizens.statement-seeds/1`:

```json
{
  "schema": "citizens.statement-seeds/1",
  "assembly": {"name": "...", "language": "it"},
  "exported_at": "2026-11-15T10:12:00Z",
  "statements": [
    {"position": 1, "statement": "..."},
    {"position": 2, "statement": "..."}
  ]
}
```

| Field | Type | Meaning |
|---|---|---|
| `schema` | string | Always `citizens.statement-seeds/1` |
| `assembly.name` | string | The assembly's name |
| `assembly.language` | string | One of `en`, `it`, `de`, `fr`, `es` |
| `exported_at` | string | Export time, UTC |
| `statements[].position` | integer | 1-based position |
| `statements[].statement` | string | The statement text. Note the field is `statement`, not `text` |

## Statement limits

* Target length under 140 characters; hard limit 400 (the PolisOrbis seed box limit), enforced on save.
* A generation produces 10 to 60 statements (the slider), one to three per finding, one idea each, declarative, neutral, no names, no table numbers, no quotations.
* Statuses: `DRAFT`, `APPROVED`, `REJECTED`, `EXPORTED`. Exported statements are marked `EXPORTED`; you can export again.

## Provenance (not exported)

Each generated statement stores the finding it was written from, the claim, the transcript excerpt (names masked) and four 0 to 2 scores (grounded, contestable, single idea, clear) for the Why panel
(migration 0042). None of this is in the export files or sent to Polis.

## Audit

Generating, adding, reviewing, deleting and exporting are audited by count and format, never by content: `seeds_generation_requested`, `seed_added`, `seed_reviewed`, `seed_deleted`, `seeds_exported`,
`seeds_approved_all`, `seeds_push_requested`, `polis_poll_published`, `polis_poll_unpublished`.
