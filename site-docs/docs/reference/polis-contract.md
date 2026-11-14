# Polis bridge contract

How Citizens talks to a Polis instance. This is condensed from the contract document kept with the Citizens-Polis fork (`docs/citizens-integration.md`). The Polis side is a fork of PolisOrbis 1.5.0
(branch `democracyroutes`); the import and ping endpoints below exist only there.

!!! info "Citizens does not expose an API to Polis"
    Every Citizens organizer route needs an authenticated organizer, and there is no API token an external service can use. The bridge receives statements that Citizens sends; it does not call Citizens.

## Authentication

Requests to the fork's Citizens endpoints carry `Authorization: Bearer <api key>`. The key is issued per Citizens installation by the Polis operator (`deploy/prod/create-apikey.sh <email>` in the fork). It is
entered in Citizens under Settings, AI, Polis together with the instance URL, and is stored like the other API keys and never shown again.

## The import call

`POST <instance>/api/v3/citizens/import`, `application/json`. The body is the `statements.json` export unchanged (see [Seeds export formats](seeds-formats.md)) with optional extra fields:

```json
{
  "schema": "citizens.statement-seeds/1",
  "assembly": { "name": "Assemblea sul centro storico", "language": "it" },
  "exported_at": "2026-10-29T10:00:00Z",
  "statements": [ { "position": 1, "statement": "..." } ],
  "topic": "optional, default: assembly.name",
  "description": "optional, shown under the title, default empty",
  "strict_moderation": false,
  "reuse": true
}
```

Response 200:

```json
{
  "conversation_id": "3hjm3feewj",
  "url": "https://polis.example.org/3hjm3feewj",
  "moderation_url": "https://polis.example.org/m/3hjm3feewj",
  "report_url": "https://polis.example.org/report/r...",
  "created": true,
  "statements": {
    "added": 12, "skipped_duplicate": 0, "failed": 0,
    "results": [ { "position": 1, "status": "success", "tid": 0 } ]
  }
}
```

### Rules

* The conversation is created active and public, with the assembly name as topic, owned by the account the key belongs to. A report (analysis page) is created with it. The voting page shows itself in the participant's browser
  language; `assembly.language` is accepted and recorded, but Polis has no per-conversation language setting.
* **Idempotent per assembly name.** A second call with the same name finds the existing conversation (`created: false`) and adds only statements whose text is new (`skipped_duplicate` counts the rest). Retrying after a
  network error is safe. `reuse: false` forces a new conversation.
* **Limits:** 1 to 200 statements, each 1 to 400 characters after trimming. Anything out of range refuses the whole call with 400 `polis_err_citizens_import_invalid` and a `details` list (`field`, `reason`).
* **No personal data.** A statement containing an email address, a phone number (8 or more digits), a table reference (`tavolo 3`, `table 12`, `Tisch`, `mesa`) or wrapped in quotation marks (a verbatim quote) refuses the
  whole call with 400 `polis_err_citizens_import_personal_data` and the offending `position`s. Citizens shows these to the organizer, marking the statements **Refused by Polis**.
* **Errors:** 401 without a key, 403 with a wrong one, 429 after 20 imports in an hour (`polis_err_citizens_import_rate_limited`).

### What Citizens stores

Per assembly: `conversation_id`, `url`, `moderation_url`, `report_url`, the time, and the `tid` per statement (migration 0041). Citizens shows the three links on the seeds card.

## The ping

`GET <instance>/api/v3/citizens/ping` with the same bearer header. Response 200:

```json
{"ok": true, "owner_email": "...", "instance": "https://polis.example.org"}
```

401 without a key and 403 with a wrong one. Citizens' **Test connection** calls it and shows whose key it is.

## How Citizens uses it

The push runs as the `PUSH_POLIS` job from `POST /api/v1/assemblies/{id}/seeds/push`. Citizens sends the same file the JSON export writes, plus the assembly name as the topic and its description. The statements sent are marked
`EXPORTED`. Publishing the voting link on the table phones is separate: `POST` and `DELETE /api/v1/assemblies/{id}/seeds/poll/publish`, with `GET .../seeds/poll-qr` for the QR code.

## Polis side: what the bridge provides

* Import a `statements.json` (or CSV) and create a conversation with those statements as seed comments, in the assembly language, with the assembly name as topic, returning the conversation id and public URL.
* Idempotency on assembly name plus statement text.
* The fork also adds `POST /api/v3/comments-bulk` and AI draft endpoints (`GET /api/v3/ai/status`, `POST /api/v3/ai/draft-statements`) which Citizens does not use.
* Not built: export of Polis results for an assembly into a documented JSON that Citizens could import into its report.

## Verified PolisOrbis 1.5.0 behaviour

Checked 2026-10-28 against a local install: authentication is a session cookie; API keys exist (`Authorization: Bearer` on the fork) but PolisOrbis cannot issue one itself; `POST /api/v3/conversations` creates a conversation;
`POST /api/v3/comments` with `is_seed: true` adds a seed and returns its `tid`; the server accepts up to 997 characters per comment while the Citizens hard limit is 400. The report page of the stock image loads d3 and Font Awesome from third-party
CDNs, while the admin and participation pages load nothing external.
