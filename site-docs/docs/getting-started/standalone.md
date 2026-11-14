# Run standalone

Standalone mode is the same app in one Docker container. It has its own sign-in, keeps
its Settings in its own database, and serves its own organizer page. You put a reverse
proxy with HTTPS in front of it. Requirements are in [Requirements](requirements.md).

## The reverse proxy

The container listens on `127.0.0.1:23000` (change the port with `CITIZENS_PORT`). It
does not do HTTPS. Your proxy must:

* terminate HTTPS;
* pass `Host`, `X-Forwarded-For` and `X-Forwarded-Proto`;
* allow request bodies of at least **6 MB**. One audio chunk is 5 MB, and the app refuses
  anything above 6 MB (`MAX_REQUEST_BYTES` in `citizens/api/limits.py`). nginx refuses more
  than 1 MB by default, so set it.

WebSocket upgrade is not needed. The app has no WebSocket endpoint for browsers.

=== "nginx"

    ```nginx
    server {
        listen 443 ssl http2;
        server_name citizens.example.org;
        # ssl_certificate / ssl_certificate_key as usual

        client_max_body_size 8m;

        location / {
            proxy_pass http://127.0.0.1:23000;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 120s;
        }
    }
    ```

=== "Caddy"

    Certificates are automatic; Caddy sets the forwarding headers itself.

    ```text
    citizens.example.org {
        request_body {
            max_size 8MB
        }
        reverse_proxy 127.0.0.1:23000
    }
    ```

## First start

```sh
cp .env.standalone.example .env.standalone
openssl rand -hex 32          # paste the result as APP_SECRET
$EDITOR .env.standalone
sh scripts/standalone-up.sh
```

Set at least `APP_SECRET` and `CITIZENS_PUBLIC_URL`. Without them the app stops at startup
and logs `missing_required_environment`. Set `CITIZENS_TRUSTED_PROXIES` too (see
[Troubleshooting](#troubleshooting)). Every variable is explained in
`.env.standalone.example` and listed in the
[configuration reference](../reference/configuration.md).

The script builds the image, starts the container, waits for `/heartbeat` and prints the
status. The first build takes a few minutes.

!!! danger "Back up APP_SECRET"
    `APP_SECRET` signs the login cookies and encrypts stored API keys and QR tokens. If you
    change it, everyone is signed out and the stored API keys become unreadable (enter them
    again in Settings). Keep a copy of `.env.standalone` with your backups.

## Accounts

Create the first administrator in one of two ways.

* Put `CITIZENS_BOOTSTRAP_ADMIN_USER` and `CITIZENS_BOOTSTRAP_ADMIN_PASSWORD` in
  `.env.standalone` before the first start. They are used once, while no account exists.
  Remove both lines afterwards and run `sh scripts/standalone-up.sh` again.
* Or use the command line. It asks for the password on the terminal:

    ```sh
    docker compose -f docker-compose.standalone.yml exec citizens \
        python -m citizens.standalone create-admin --username anna --email anna@example.org
    ```

Other operator commands: `set-password --username anna` (a lost password when mail is not
set up) and `list-users`.

Open `CITIZENS_PUBLIC_URL` in a browser and sign in. To add an organizer, go to
**Settings, Organisation, Users** and add the person. With SMTP set up, they get a mail
with a link to choose a password. Without it, no usable link exists: the log shows the mail
with the link redacted. Set the password from the command line instead:

```sh
docker compose -f docker-compose.standalone.yml exec citizens \
  python -m citizens.standalone set-password --username anna
```

Links expire after 7 days (invitations) or 2 hours (resets). The same card sends a new
link, changes roles, disables accounts and deletes them.

## What the phones open

The QR codes and the printed sheets point at `https://citizens.example.org/recorder.html`,
built from `CITIZENS_PUBLIC_URL`. Phones need no account. Check the address on a printed
sheet before an event.

## Settings

Settings is the same page as in Nextcloud mode: speech-to-text providers, analysis,
branding, retention, and the built-in Vosk engine with its model installs. See the
[Settings reference](../admin/settings.md). The difference is where it is stored: in the
app database, not in Nextcloud. The built-in Vosk engine is switched on in Settings; there
is no environment variable for it. Large models need the 6 GB memory limit.

## Backups

The data is in the Docker volume `citizens_standalone_data`. Compose adds the project name
in front, so find the real name:

```sh
docker volume ls | grep citizens_standalone_data
sh scripts/backup-citizens-data.sh <that volume name>
```

The script writes a consistent copy of the database and a tarball of the audio,
transcripts and logs. It needs `sqlite3` on the host. Set `BACKUP_ROOT` (default
`/root/backups`) and `CITIZENS_BACKUP_REMOTE` to copy off the machine. Restoring works as
described in [Backups and restore](../admin/backups.md). Also keep a copy of
`.env.standalone`.

## Updates

```sh
git pull
sh scripts/standalone-up.sh
```

The database upgrades itself at startup. Back up first. Stop the app with
`sh scripts/standalone-down.sh`; the data volume is kept.

## Logs

```sh
docker compose -f docker-compose.standalone.yml logs -f citizens
```

Files are in the volume under `logs/` (`citizens.jsonl`, 10 MB x 5). Change the detail with
`CITIZENS_LOG_LEVEL`.

## Troubleshooting

* **The container restarts and the log says `mode_invalid`.** `CITIZENS_MODE` is not exactly
  `standalone` (or `nextcloud`). Fix the typo.
* **The log says `missing_required_environment`.** The log lists the variables:
  `APP_SECRET` or `CITIZENS_PUBLIC_URL` is empty.
* **Sign-in works but you are signed out at once.** When `CITIZENS_PUBLIC_URL` starts with
  `https`, the session cookie is marked Secure. If the browser reaches the app over plain
  HTTP, it drops the cookie. Make sure the browser uses the HTTPS address, and that the
  proxy is what serves it.
* **Too many sign-in attempts block everybody, or the log shows one address for all
  visitors.** Rate limiting sees only the proxy. Set `CITIZENS_TRUSTED_PROXIES` to the proxy
  address as the container sees it (for a proxy on the host, the Docker network gateway),
  then run `sh scripts/standalone-up.sh`.
* **Uploads fail with 413.** The proxy body limit is below 6 MB.
* **The QR codes show the wrong address.** Fix `CITIZENS_PUBLIC_URL`.
* **No mail arrives.** Check `CITIZENS_SMTP_URL` and `CITIZENS_MAIL_FROM`; the log shows the
  send error. The invitation link is also in the log.
* **A large Vosk model is refused.** The container does not have enough free memory. Raise
  `mem_limit` and `memswap_limit`.

## How it differs from Nextcloud mode

* Organizers have accounts in the app, not Nextcloud users.
* Settings are kept in the app database, not in Nextcloud's app config.
* There is no app store install and no AppAPI. You run the container yourself.
* No Nextcloud notifications yet.
* OpenID Connect sign-in is planned, not built.
* Recording, transcription, analysis and reports work the same way.
