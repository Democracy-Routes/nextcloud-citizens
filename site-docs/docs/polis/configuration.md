# Configuration variables

Polis is configured by environment variables. There are two kinds:

* **Runtime** variables, read by the server and maths containers from `deploy/<local|prod>/.env` (written on first run by
  `polis.sh`, git-ignored, holding secrets).
* **Build-time** variables, the `P_*` values, the client settings and `EMBED_SERVICE_HOSTNAME`. They are baked into the
  file-server image from `deploy/branding.env` (public, not secret) and need `./deploy/build-images.sh file-server` to change.

The reference list is `example.env`, which is PolisOrbis's template plus the fork's additions. It is for the development workflow;
the production values come from the two files above. Secrets (`POSTGRES_PASSWORD`, `WEBSERVER_PASS`, `AI_PROVIDER_API_KEY`, the
OpenID client secret) never go into git or chat.

## General

| Variable | Meaning |
|---|---|
| `DEV_MODE` | `true` for development; **`false` in production** |
| `MATH_ENV` | `prod`, `preprod` or `dev` for the maths service |
| `ADMIN_UIDS`, `ADMIN_EMAILS` | Lists of administrator users and addresses; `[]` in both generated stacks |
| `SERVER_ENV_FILE` | Env file the server container reads; set by `polis.sh` |
| `SERVER_LOG_LEVEL` | Log level, default `info` |
| `SERVER_LOG_TO_FILE` | Also write logs to `server/logs` (a volume under compose) |
| `GIT_HASH` | Optional build identifier for debugging; `build-images.sh` passes the short hash to the file-server |
| `CACHE_MATH_RESULTS` | Cache results from the maths service; default true |
| `BACKFILL_COMMENT_LANG_DETECTION`, `RUN_PERIODIC_EXPORT_TESTS` | Upstream flags, default false |
| `TAG`, `COMPOSE_PROJECT_NAME` | Docker conveniences; `polis.sh` sets the project to `citizens-polis-<target>` |

## Domain and cookies

| Variable | Meaning |
|---|---|
| `DOMAIN_OVERRIDE` | The public host name, in production. The cookie domain is otherwise taken from the request's `Origin` header, so a non-browser client must send `Origin: <instance URL>` |
| `API_PROD_HOSTNAME` | Public host name; set both this and `DOMAIN_OVERRIDE` to the same value on a custom domain |
| `API_DEV_HOSTNAME` | Development host, default `localhost` (`localhost:8190` locally) |
| `EMBED_SERVICE_HOSTNAME` | Embed host name; in production it matches the public host. Build-time |
| `DOMAIN_WHITELIST_ITEM_01` to `_08` | The server's domain whitelist. The local stack refuses `127.0.0.1`, hence `localhost` |
| `SERVICE_URL` | Full URL of the API server; only needed when static files are on another domain |
| `STATIC_FILES_HOST`, `STATIC_FILES_PORT`, `STATIC_FILES_ADMIN_PORT`, `STATIC_FILES_PARTICIPATION_PORT` | Where the server finds the file-server (`file-server`, `8080`) |
| `API_SERVER_PORT` | The server's port inside the container, `5000` |
| `HTTP_PORT`, `HTTPS_PORT` | Used only by upstream's `nginx-proxy`, which the kit does not start |

## Database

| Variable | Meaning |
|---|---|
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT`, `POSTGRES_HOST` | The database; the generated stack uses database `polis`, user `postgres` and a random password |
| `DATABASE_URL` | Connection string the server and maths use |
| `READ_ONLY_DATABASE_URL` | Optional read replica |
| `WEBSERVER_USERNAME`, `WEBSERVER_PASS` | Basic-auth pair between the maths and API services (deprecated upstream; a random password is generated) |

## Purge

| Variable | Meaning |
|---|---|
| `PRUNE_ENABLED` | `true` installs the nightly deletion and registers `POST /api/v3/prune`. **`false` in every stack here**; see [the purge](deployment.md#the-purge-and-the-data-loss-of-2-november-2026) |
| `PRUNE_OLDER_THAN` | Seconds without a change before a conversation is deleted, default `172800` |
| `PRUNE_SCHEDULE` | Cron schedule, default `0 3 * * *` |

## E-mail and outbound services (all off)

| Variable | Meaning |
|---|---|
| `EMAIL_TRANSPORT_TYPES` | Empty disables all outbound e-mail. Polis cannot e-mail anyone |
| `POLIS_FROM_ADDRESS`, `ADMIN_EMAIL_*` | Sender and administrator addresses; unused while mail is off |
| `SHOULD_USE_TRANSLATION_API` | `false`; the translation API is Google's and would send text out |
| `AKISMET_ANTISPAM_API_KEY`, `MAXMIND_LICENSEKEY`, `MAXMIND_USERID`, `GA_TRACKING_ID`, `FB_APP_ID`, `ENABLE_TWITTER_WIDGETS` | Third-party credentials and widgets; blank or false |
| `P_OPENID_ENABLED` and the other `P_OPENID_*` | OpenID Connect sign-in; `false` here |

## Public branding (build-time)

| Variable | Meaning |
|---|---|
| `P_HOME_NAME` | Organisation name (`Democracy Routes` here) |
| `P_TITLE` | Site title (`Polis` here) |
| `P_CLAIM`, `P_DESCRIPTION` | Tagline and description |
| `P_LOGO_URL`, `P_LOGO_ICO_URL` | Where the logo links, and the favicon path |
| `P_HOME_URL` | Where **Back to the start** goes after the last statement, default `/home` |
| `P_DOC_URL` | Documentation link |
| `P_REPO_URL` | Source link, shown in the footer (AGPL section 13) |
| `P_ORBIS_RATING` | `true` shows PolisOrbis's satisfaction survey on the policy-analysis view; off unless set |

## Legal pages (build-time)

Leave `P_TOS_URL` and `P_PRIVACY_POLICY_URL` blank to use the built-in `/tos` and `/privacy` pages (English and Italian); set them to
use external pages instead.

| Variable | Meaning |
|---|---|
| `P_OPERATOR_NAME`, `P_OPERATOR_ADDRESS`, `P_OPERATOR_EMAIL` | Who operates the installation. The operator block becomes a red warning until name and e-mail are set |
| `P_OPERATOR_DPO` | Data-protection contact |
| `P_HOSTING_COUNTRY` | Where the installation is hosted |
| `P_SUPERVISORY_AUTHORITY` | The authority named in the "your rights" section |
| `P_RETENTION` | A phrase such as "12 months after a conversation closes" |
| `P_GOVERNING_LAW` | Governing law for the terms |

## AI statement drafting

Off until `AI_PROVIDER_BASE_URL` and `AI_MODEL` are set. Any OpenAI-compatible chat API works. After a change run
`./deploy/polis.sh prod up`.

| Variable | Meaning |
|---|---|
| `AI_PROVIDER_BASE_URL` | The provider's `/v1` URL. Blank switches the feature off |
| `AI_PROVIDER_API_KEY` | The provider key (a secret); blank for a local Ollama |
| `AI_MODEL` | Model name |
| `AI_PROVIDER_NAME`, `AI_PROVIDER_REGION`, `AI_PROVIDER_PRIVACY_URL` | Shown on the privacy page; needed for a provider the server does not know |
| `AI_JSON_MODE` | `auto`, `on` or `off`: ask the provider for JSON output. `auto` is on for Mistral and OpenAI |

Preset base URLs listed in the runbook: Ollama Cloud `https://ollama.com/v1`, Mistral `https://api.mistral.ai/v1`, OpenAI
`https://api.openai.com/v1`, Anthropic's OpenAI-compatible endpoint `https://api.anthropic.com/v1`, Gemini
`https://generativelanguage.googleapis.com/v1beta/openai`, a local Ollama `http://<host>:11434/v1`; vLLM, Groq and OpenRouter with
their `/v1` URL. Only Ollama Cloud and a fake test provider have been exercised. The instance in use since 2026-10-29 is Ollama
Cloud with the model `glm-5.3`.
