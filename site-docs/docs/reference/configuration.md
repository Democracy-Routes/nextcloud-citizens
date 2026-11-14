# Configuration variables

Two kinds of configuration exist. **Environment variables** configure the container and are read at startup. **Settings keys** configure providers and
organisation data, are changed at runtime from the Settings page, and are stored in Nextcloud's app configuration (Nextcloud mode) or in an app database table
(standalone mode). The Settings keys are listed in the [Settings reference](../admin/settings.md#settings-keys).

## Environment: both modes

| Variable | Default | Meaning |
|---|---|---|
| `APP_ID` | `citizens` | App id (set by AppAPI) |
| `APP_VERSION` | the built-in version | Reported version (set by AppAPI) |
| `APP_HOST`, `APP_PORT` | `0.0.0.0`, `23000` | Listen address |
| `APP_SECRET` | none, required | Shared secret. In Nextcloud mode AppAPI generates it. In standalone mode it signs cookies and encrypts stored API keys and QR tokens |
| `APP_PERSISTENT_STORAGE` | `persistent_storage` | Data directory (`/data` in containers) |
| `CITIZENS_MODE` | `nextcloud` | `nextcloud` or `standalone`. Any other value stops startup with `mode_invalid` |
| `CITIZENS_PUBLIC_URL` | empty | The address phones open and QR codes carry. Required in standalone mode. In Nextcloud mode, empty means use `overwrite.cli.url` |
| `CITIZENS_JOB_WORKERS` | `10` | Jobs run at once; `1` is strictly sequential |
| `CITIZENS_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

## Environment: Nextcloud mode

| Variable | Meaning |
|---|---|
| `NEXTCLOUD_URL` | Required. The address the app container uses to reach Nextcloud (set by AppAPI) |
| `HP_SHARED_KEY` | Present for HaRP daemons: the app then listens on `/tmp/exapp.sock` and runs `frpc` |

Pass extra variables at registration with `--env`, for example `--env CITIZENS_PUBLIC_URL=https://cloud.example.org`.

## Environment: standalone mode

From `.env.standalone.example`. Copy it to `.env.standalone`; the file holds secrets, so keep it out of git. No quotes around values, no spaces around `=`.

| Variable | Default | Meaning |
|---|---|---|
| `CITIZENS_MODE` | none | Must be exactly `standalone` |
| `APP_SECRET` | none | Required. Create one with `openssl rand -hex 32`. If you change it, everyone is signed out and stored API keys become unreadable. Back it up |
| `CITIZENS_PUBLIC_URL` | none | Required. With `https` and no trailing slash. Used by QR codes, invitation mails and the Secure cookie flag |
| `CITIZENS_TRUSTED_PROXIES` | empty | Comma-separated addresses whose `X-Forwarded-For` is believed, as the container sees the proxy (a Docker network gateway such as `172.18.0.1` for a proxy on the same host). Empty: the direct peer is the client, and login rate limiting sees every visitor as the proxy |
| `CITIZENS_SMTP_URL` | empty | `smtp://user:pass@host:587` (STARTTLS), `smtps://user:pass@host:465` (implicit TLS), `smtp://relay:25` (plain, local relay only). Percent-encode special characters in the password. Empty: no mail is sent and no link is usable |
| `CITIZENS_MAIL_FROM` | empty | Sender of invitation and reset mails |
| `CITIZENS_BOOTSTRAP_ADMIN_USER`, `CITIZENS_BOOTSTRAP_ADMIN_PASSWORD` | empty | First administrator, used once while no account exists. Remove after the first start |
| `CITIZENS_SESSION_DAYS` | `14` | How many days a browser stays signed in |
| `CITIZENS_PORT` | `23000` | Host port (read by `docker-compose.standalone.yml` and `standalone-up.sh`) |

The built-in Vosk engine needs no variable: switch it on in Settings. Give the container more memory for large models (`mem_limit` in the Compose file).

## Environment: scripts

| Variable | Used by | Meaning |
|---|---|---|
| `CITIZENS_VOSK_BUILTIN=1` | `scripts/event-up.sh` | Raises container memory to 3500m and stops the separate Vosk container |
| `CITIZENS_MEMORY` | `scripts/event-up.sh` | Memory limit (default `2g`) |
| `CITIZENS_BACKUP_REMOTE`, `BACKUP_ROOT` | `scripts/backup-citizens-data.sh` | rsync target and backup root (default `/root/backups`) |
| `VOSK_MODEL_IDLE_SECONDS`, `VOSK_MODEL_CACHE` | `scripts/vosk-up.sh` server | Idle unload (default 30 minutes) and models held (default 2) |
| `CONTAINER`, `VOLUME_DIR` | `scripts/event-status.sh` | Override container and data volume discovery |

## Operator commands (standalone)

```sh
docker compose -f docker-compose.standalone.yml exec citizens python -m citizens.standalone create-admin --username anna --email anna@example.org
docker compose -f docker-compose.standalone.yml exec citizens python -m citizens.standalone set-password --username anna
docker compose -f docker-compose.standalone.yml exec citizens python -m citizens.standalone list-users
```

## Limits worth knowing

| Limit | Value | Where |
|---|---|---|
| Request body accepted | 6 MB (`MAX_REQUEST_BYTES`, `citizens/api/limits.py`) | The app; set the proxy to at least 8 MB |
| Audio chunk | 5 MB (`MAX_CHUNK_BYTES`), parts of 1 MiB for oversized chunks | Recorder and server |
| Upload part (import and attach) | 5 MB | Uploads API |
| Phone session lifetime | 16 hours from last contact | Recorder |
| Facilitator session | 12 hours | Facilitator phone |
| Added-recorder or added-table QR | 15 minutes, single use | Capabilities |
| QR invite | 30 days | Table codes |
| Silent recorder auto-close | 300 seconds | Sweep |
| Finish-from-Live-tab grace | 90 seconds | Sweep |
| Stalled-device takeover | 120 seconds | Recorder start |
| Retention default | `0` (keep indefinitely) | Settings |
