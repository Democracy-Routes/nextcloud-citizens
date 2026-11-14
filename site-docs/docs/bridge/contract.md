# Contract

The technical contract between Citizens and a Polis instance. The Polis side is the Citizens-Polis fork of PolisOrbis 1.5.0
(`docs/citizens-integration.md` and `server/src/routes/citizensImport.ts` in its repository); the Citizens side is
`citizens/services/polis.py`. This page was written against both. For the other routes of the fork see the
[Polis API reference](../polis/api.md).

!!! info "Citizens does not expose an API to Polis"
    Every Citizens organizer route needs an authenticated organizer, and there is no API token an external service can use. The
    bridge receives statements that Citizens sends; it does not call Citizens. Polis does not know the assembly beyond its name and
    cannot report back by id.

## Authentication

Requests to the fork's Citizens endpoints carry `Authorization: Bearer <api key>`. The key is issued per Citizens installation by the
Polis operator (`deploy/prod/create-apikey.sh <email>`), tied to one team account, entered in Citizens under Settings, AI, Polis
together with the instance URL, and stored like the other API keys. Setup and rotation are in
[Connecting an installation](setup.md). If the request also carries a Polis session cookie, the cookie is used instead of the
Bearer header; Citizens sends none.

## The import call

`POST <instance>/api/v3/citizens/import`, `application/json`. The body is the `statements.json` export **unchanged** (see
[Seeds export formats](../reference/seeds-formats.md)) with optional extra fields:

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

| Field | Rule |
|---|---|
| `schema` | Must be `citizens.statement-seeds/1` |
| `assembly.name` | Required, 1 to 1000 characters after trimming. Becomes the topic and the idempotency key |
| `assembly.language` | One of `en`, `it`, `de`, `fr`, `es`; anything else is ignored. Accepted and recorded, but Polis has **no per-conversation language setting**: the voting page shows itself in the participant's browser language |
| `statements` | A non-empty array of at most **200** |
| `statements[].statement` | Required, **1 to 400 characters** after trimming |
| `statements[].position` | Optional number; statements are ordered by it (file order breaks ties); a missing position is the row's index plus one |
| `topic` | Optional, 1 to 1000 characters; default the assembly name |
| `description` | Optional, up to 50000 characters; default empty |
| `strict_moderation` | Optional boolean (or the strings `true`, `false`); default `false` |
| `reuse` | Optional boolean; default `true` |

Citizens sends the file the JSON export writes plus `topic` (the assembly name) and `description` (the assembly description cut to
2000 characters). It does not send `strict_moderation` or `reuse`, so the defaults apply.

### Response 200

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

`report_url` is `null` if the conversation has no report. Each result has `position`, `status` (`success`, `skipped` or `error`),
`tid` (the Polis comment id, present on success) and `reason` on the others.

### Rules

* The conversation is created **active and public**, with the assembly name as topic, **owned by the account the key belongs to**. A
  report (analysis page) is created with it.
* **Idempotent per assembly name and account.** The conversation is found by owner plus a context of `citizens:` followed by the
  assembly name (whitespace collapsed, trimmed, cut at 990 characters). A second call with the same name finds the existing
  conversation (`created: false`) and adds only statements whose text is new (`skipped_duplicate` counts the rest). Retrying after a
  network error is safe. `reuse: false` forces a new conversation. Two different accounts sending the same name get two
  conversations.
* **Limits:** 1 to 200 statements, each 1 to 400 characters after trimming. Anything out of range refuses the whole call with 400
  `polis_err_citizens_import_invalid` and a `details` list of `field` and `reason`.
* **No personal data.** A statement that matches any of these rules refuses the **whole** call with 400
  `polis_err_citizens_import_personal_data` and the offending `position`s (each with a `reason`):

    | Rule | What matches |
    |---|---|
    | E-mail address | `name@domain.tld` |
    | Phone number | 8 or more digits, optionally separated by spaces, dots, dashes or slashes, optionally starting with `+` or `0` or `(0`. Years and small counts have fewer digits |
    | Table reference | The word `table`, `tavolo`, `tisch` or `mesa` followed by a number, optionally with `n`, `n°`, `no.` or `#` between (`tavolo 3`, `table 12`) |
    | Verbatim quote | The whole statement wrapped in quotation marks (`"`, `“…”`, `«…»`, `‘…’`, `'…'`) |

    The guard is deliberately simple and errs on the side of refusing; it is the second line after Citizens' own rule that the
    statements carry no names, table numbers or quotations. The documents of both repositories list the table words alone ("Tisch",
    "mesa"), but the code requires a number after them.
* **Rate limit:** 20 imports per hour per account, in memory (a restart resets it), checked after validation. 429
  `polis_err_citizens_import_rate_limited`.
* **Errors:** 401 without a key, 403 with a wrong one, 400 as above, 429, 500 `polis_err_citizens_import`.

### What Citizens stores

Per assembly (migration 0041): `conversation_id`, `url`, `moderation_url`, `report_url`, the time of the push (`pushed_at`) and, when
the poll is put on the devices, `published_at`. Per statement: the Polis `tid` and the conversation id, **only for statements Polis
reported as `success`**: a statement skipped as a duplicate on a re-send keeps the `tid` it got the first time. Citizens shows the
three links on the seeds card. The statements sent are marked **EXPORTED**.

## The ping

`GET <instance>/api/v3/citizens/ping` with the same bearer header. Response 200:

```json
{"ok": true, "owner_email": "...", "instance": "https://polis.example.org"}
```

401 without a key and 403 with a wrong one. Citizens' **Test connection** calls it and shows whose key it is. `owner_email` is the
stored address of the key's account.

## How Citizens runs it

* The push is the `PUSH_POLIS` job, queued by `POST /api/v1/assemblies/{id}/seeds/push` on the Citizens side. The network call has a
  120 second timeout and never runs inside a request or a database transaction.
* A key problem, refused content or a missing endpoint is a permanent failure; a 429 or a network failure is not permanent. For
  a personal-data refusal Citizens marks the named positions **Refused by Polis**.
* Publishing the voting link on the table phones is separate: `POST` and `DELETE /api/v1/assemblies/{id}/seeds/poll/publish`
  (publishing needs a successful send first, otherwise 409), with `GET .../seeds/poll-qr` for the QR code. Withdrawing from the
  devices does not touch the Polis conversation.
* The instance URL and key are the Settings keys `polis_url` and `polis_api_key`.

## Verified PolisOrbis 1.5.0 behaviour

Checked 2026-10-28 against a local install: authentication is a session cookie; API keys exist (`Authorization: Bearer` on the fork)
but PolisOrbis cannot issue one itself; `POST /api/v3/conversations` creates a conversation; `POST /api/v3/comments` with
`is_seed: true` adds a seed and returns its `tid`; the server accepts up to 997 characters per comment while the hard limit used
here is 400, the size of the seed box. The report page of the stock image loaded d3 and Font Awesome from third-party CDNs, which
the fork removed; the admin and participation pages load nothing external.

## Not built

Pulling Polis results back into Citizens, a documented JSON of an assembly's Polis results that Citizens could import into its
report. See [Roadmap](roadmap.md).
