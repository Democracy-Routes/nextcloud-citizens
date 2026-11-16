# API reference

This page lists the routes the fork adds and the upstream routes that the Citizens bridge and the organizer pages rely on.
Everything is under `/api/v3/`. Request and response bodies are JSON. Error codes begin `polis_err_`. The route table is in `server/app.ts`; the handlers are in `server/src/routes/`.

The bridge contract, with examples and the Citizens side, is in [Citizens + Polis: Contract](../bridge/contract.md).

## Authentication

Routes that need a login accept, checked in this order:

1. an API key in the `x-sandstorm-app-polis-apikey` header or a `polisApiKey` body field (upstream);
2. the session cookie set by sign-in (`token2`), the way the organizer pages authenticate;
3. `Authorization: Bearer <api key>` (added by this fork, used by Citizens);
4. HTTP Basic with the API key as the user name and any password (upstream).

A cookie therefore wins over a Bearer header if both are sent. API keys have the shape `pkey_` plus 17 characters, are tied to one
team account, and are issued and revoked by script only (see [Deployment](deployment.md#team-accounts-and-api-keys)); PolisOrbis has
no way to issue one itself. Sign-in is `POST /api/v3/auth/login` (`email`, `password`); a non-browser client must send
`Origin: <instance URL>` or the cookie is set for the wrong domain and dropped, and must send the hashed
`md5(email)@dummy.net` form of the address, as the website's forms do.

| Status | Meaning |
|---|---|
| 401 `polis_err_auth_token_not_supplied` | No credentials on a route that needs them |
| 403 `polis_err_auth_no_such_api_token` | An API key that does not exist (revoked or wrong) |
| 403 `polis_err_post_comment_auth` | The caller is not a moderator of that conversation |
| 400 | A validation or personal-data refusal; see each route |
| 404 `polis_err_ai_not_configured` | AI drafting is off |
| 429 | A rate limit; see below |
| 5xx | `polis_err_citizens_import`, `polis_err_citizens_ping`, `polis_err_post_comments_bulk`, `polis_err_ai_*`: server or provider failure |

## Rate limits

Limits are kept in memory per user account, in a sliding window. A server restart resets them.

| Route | Limit | Error |
|---|---|---|
| `POST /api/v3/citizens/import` | 20 per hour per account | 429 `polis_err_citizens_import_rate_limited` |
| `POST /api/v3/ai/draft-statements` | 30 per hour per account | 429 `polis_err_ai_rate_limited` |

Two keys on the same account share the import budget. For the import, a call refused for validation or personal data does not use up
the budget, because those checks run first.

## POST /api/v3/citizens/import

Creates (or finds) a conversation and its report and adds the seed statements, in one call. Authentication: API key. Full
description in [Contract](../bridge/contract.md).

Body: the Citizens `statements.json` export (`schema` `citizens.statement-seeds/1`, `assembly.name`, optional `assembly.language`,
`statements[]` with `position` and `statement`) plus optional `topic`, `description`, `strict_moderation`, `reuse`. Limits: 1 to 200
statements of 1 to 400 characters.

Response 200: `conversation_id`, `url`, `moderation_url`, `report_url`, `created`, and `statements` with `added`,
`skipped_duplicate`, `failed` and one result per statement (`position`, `status`, `tid`, `reason`).

Errors: 400 `polis_err_citizens_import_invalid` (with `details`: `field`, `reason`), 400 `polis_err_citizens_import_personal_data`
(with `details`: `position`, `reason`), 401, 403, 429, 500.

## GET /api/v3/citizens/ping

Authentication: API key. Response 200:

```json
{"ok": true, "owner_email": "...", "instance": "https://polis.example.org"}
```

`owner_email` is the stored e-mail of the key's account, which for accounts made by the scripts is the hashed `...@dummy.net` form.
401 without a key, 403 with a wrong one. Nothing else is returned.

## POST /api/v3/comments-bulk

Adds seed statements from a CSV. Authentication: session or key, and the caller must be a moderator of the conversation.

Body:

```json
{ "conversation_id": "3hjm3feewj", "csv": "position,statement\n1,\"...\"\n" }
```

The accepted headers are `comment_text`, `comment_text,original_id`, `statement` and `position,statement`; see
[Running a conversation](organizers.md#csv-upload). Response 200:

```json
{ "results": [ { "txt": "...", "status": "success", "tid": 12 },
               { "txt": "...", "status": "skipped", "reason": "polis_err_post_comment_duplicate" } ],
  "currentPid": 3 }
```

`status` is `success`, `skipped` (reasons `polis_err_param_missing_txt`, `polis_err_comment_too_long`,
`polis_err_post_comment_duplicate`) or `error` (`polis_err_post_comment`). Errors: 400 `polis_err_param_missing_csv`,
`polis_err_csv_header`, `polis_err_csv_malformed`; 403 `polis_err_post_comment_auth`.

## GET /api/v3/ai/status

Public (optional auth). Whether AI drafting is on and who the provider is:

```json
{ "enabled": true, "provider": "Ollama Cloud", "region": "...", "privacyUrl": "https://..." }
```

When off: `{"enabled": false, "provider": null, "region": null, "privacyUrl": null}`. The privacy page reads it.

## POST /api/v3/ai/draft-statements

Moderators only. Asks the configured provider for statements; nothing is stored.

| Field | Type | Meaning |
|---|---|---|
| `conversation_id` | string | The conversation (its title and description are background) |
| `request` | string, 1 to 2000 | The subject, in the organizer's words |
| `count` | integer 1 to 40 | How many statements, default 10 |
| `language` | string, 1 to 10 | `en`, `it`, `de`, `fr`, `es`; anything else means the language of the request |
| `instruction` | string, 1 to 2000 | Optional extra instruction |
| `kept` | array of strings | On a refinement, the statements already kept (up to 60, each cut to 400 characters) |

Response 200: `{"statements": ["..."], "provider": "..."}`. One correction round-trip is made if the first answer cannot be parsed.
Errors: 404 `polis_err_ai_not_configured`, 403, 429 `polis_err_ai_rate_limited`, 502 `polis_err_ai_bad_response` or
`polis_err_ai_upstream`. The provider call times out after 60 seconds.

## GET /api/v3/listed-conversations

Public, no login, cached for 30 seconds. The open, non-draft conversations whose organizer switched on the home-page listing,
newest first, at most 50:

```json
{ "conversations": [ { "conversation_id": "3hjm3feewj", "topic": "...", "description": "...",
                       "participant_count": 12, "created": <number>, "report_id": "r..." } ] }
```

`description` is cut to 300 characters; `report_id` is `null` when there is no report. Listing conversations by `context` without a
login, which upstream allowed, is refused.

## Upstream routes the bridge relies on

These routes are as in PolisOrbis 1.5.0. Citizens does not need to call them, because the import call replaces them, but the import
builds on them.

| Route | Use |
|---|---|
| `POST /api/v3/auth/login` | Sign in (`email`, `password`) |
| `POST /api/v3/auth/new` | Create an owner account (`hname`, `email`, `password`, `gatekeeperTosPrivacy: true`). Blocked at the public proxy |
| `POST /api/v3/conversations` | Create a conversation (`topic`, `description`, `is_active`, `is_draft`); returns `url` and `conversation_id` |
| `POST /api/v3/comments` | Add a statement (`conversation_id`, `txt` up to 997 characters, `is_seed: true`, `vote: 0`); returns the `tid` |
| `GET /api/v3/comments?conversation_id=<id>` | List statements with `tid`, `txt`, `is_seed`; needs no login for a public conversation |
| `POST /api/v3/prune` | The sandbox purge. Only registered when `PRUNE_ENABLED=true`; blocked at the proxy |

Pulling results out of Polis for Citizens (`GET /api/v3/citizens/results/{conversation_id}`) is not built; see the
[roadmap](../bridge/roadmap.md).
