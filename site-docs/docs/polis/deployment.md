# Deployment (self-hosting kit)

The repository carries everything needed to run Polis: a script for the local or the production stack, an image build script,
overrides, an nginx site, account and key scripts, and SQL for database changes. This page is the runbook, from
`docs/production.md`, `docs/host.md` and the `deploy/` directory.

!!! warning "Backups do not exist, and the purge once deleted data"
    Read [Backups](#backups) and [the purge](#the-purge-and-the-data-loss-of-2-november-2026) before putting data you care about
    on an instance.

## Components and images

`deploy/polis.sh` starts four services; upstream's `nginx-proxy` is never started (the Polis server already serves the clients
through `file-server`, and TLS comes from the host's front proxy).

| Service | Image | Memory cap | Notes |
|---|---|---|---|
| `server` | `citizens-polis/server:1.5.0-dr1` (built here) | 512 MB | Node API; prod listens on `127.0.0.1:8192`, local on `127.0.0.1:8190` |
| `math` | `registry.gitlab.com/copernicani/polisorbis/codebase/math:1.5.0` | 768 MB | JVM sized with `-XX:MaxRAMPercentage=60` |
| `postgres` | `registry.gitlab.com/copernicani/polisorbis/codebase/postgres:1.5.0` | 256 MB | volumes `postgres` and `backups` |
| `file-server` | `citizens-polis/file-server:1.5.0-dr1` (built here) | 128 MB | serves the three web clients |

Every container has `mem_limit` equal to `memswap_limit`, so none can swap. The caps total about 1.7 GB; the prod stack uses about
600 MB in practice. Production containers have `restart: unless-stopped`. The compose project names are `citizens-polis-prod`
and `citizens-polis-local`.

## polis.sh

Run from the repository root:

```sh
./deploy/polis.sh local up        # also: down, ps, logs [service]
./deploy/polis.sh prod up
```

* **Local** listens on `127.0.0.1:8190`; from a laptop use `ssh -L 8190:127.0.0.1:8190 <host>` and open
  `http://localhost:8190/home`. Use `localhost`: the server's domain whitelist refuses `127.0.0.1`.
* **Prod** listens on `127.0.0.1:8192` behind the host nginx.
* Both listen on `127.0.0.1` only. **Run one at a time**: the host is short of RAM.
* On first run the script writes `deploy/<target>/.env` (git-ignored, mode `umask 077`) with fresh random database and math
  passwords and every outbound service off: no e-mail, translation, analytics, spam check or social login, `PRUNE_ENABLED=false`,
  and the AI provider blank. In prod it also sets `DEV_MODE=false` and `DOMAIN_OVERRIDE`, `API_PROD_HOSTNAME` and
  `EMBED_SERVICE_HOSTNAME` to the public host name.
* `up` pulls the images (failures ignored) and runs `docker-compose up -d --no-build`. After editing `.env`, use `up` again: a
  plain `docker restart` keeps the old environment.

## Building the images

```sh
./deploy/build-images.sh [server|file-server|all] [tag]   # tag defaults to 1.5.0-dr1
```

Builds run with `--memory 1500m --memory-swap 3000m` because the host is short of RAM; image builds need about 1.5 GB, so **stop
the local stack first**. The file-server image is built with the public values of `deploy/branding.env` passed as build arguments
plus the short git hash.

## Branding and operator values

`deploy/branding.env` is not secret and is read at build time. It sets the name and logo, the claim and description, the source
link (`P_REPO_URL`, which the footer shows for AGPL section 13), `P_HOME_URL` and the operator details used by the legal pages.
Changing it needs a rebuild of the file-server image. Fields marked "owner to fill" (postal address, DPO, hosting country,
supervisory authority, retention, governing law) show as "[not set]" on the privacy page until filled. Every variable is listed in
[Configuration](configuration.md). The design tokens are in [Architecture](architecture.md#design-tokens).

## The nginx site

`deploy/prod/nginx/polis.democracyroutes.com` is the **reference** site file. It is copied to `/etc/nginx/sites-available/` and
linked from `sites-enabled`. It:

* returns 403 on `POST /api/v3/auth/new` and redirects `/createuser` to `/signin`, so only the team has accounts (voting stays
  open to anyone with a link);
* returns 403 on `/api/v3/prune`;
* proxies everything else to `127.0.0.1:8192` with `Host`, `X-Real-IP`, `X-Forwarded-For` and `X-Forwarded-Proto`, a 300 s read
  timeout, `X-Content-Type-Options: nosniff` and a `Referrer-Policy`;
* redirects port 80 to HTTPS.

!!! note "On the Democracy Routes host the TLS listener is not port 443"
    On this host, port 443 belongs to a stream SNI demux (`/etc/nginx/streams.d/turn443.conf`) that sends every HTTPS name to
    `127.0.0.1:8443` with `proxy_protocol`. The site file therefore has `listen 127.0.0.1:8443 ssl proxy_protocol;`, and the real
    client address comes from a global setting (`conf.d/00-realip-proxy-protocol.conf`). A host with a plain nginx would listen on
    `443 ssl` instead; keep the three `location` blocks that refuse sign-up and the purge.

The route `POST /api/v3/citizens/import` is **not** blocked by the proxy: a wrong or missing key gets 401 or 403.

## Certificates

Let's Encrypt, renewed by the host's certbot timer. First activation:

1. `./deploy/build-images.sh all`
2. `./deploy/polis.sh prod up`, then `curl -s http://127.0.0.1:8192/api/v3/testConnection`
3. Put **only the port-80 server block** in `/etc/nginx/sites-available/polis.democracyroutes.com`, link it into `sites-enabled`,
   `nginx -t && systemctl reload nginx`, then `certbot certonly --nginx -d polis.democracyroutes.com`
4. Copy the full site file over it and `nginx -t && systemctl reload nginx`
5. Create the team accounts (below)

## Team accounts and API keys

Run these on the host, in a terminal. Sign-up only works from the host, against `127.0.0.1:8192`.

| Script | Purpose |
|---|---|
| `deploy/prod/create-account.sh` | Asks for name, e-mail and password; stores `md5(e-mail)@dummy.net`. |
| `deploy/prod/reset-password.sh` | Sets a new password, hashed with the server's bcryptjs (cost 12); the password never appears in a command line. |
| `deploy/prod/create-apikey.sh <email>` | Issues an API key (`pkey_` plus 17 characters) for an existing account. Printed once. |
| `deploy/prod/delete-apikey.sh <email>` | Revokes every key of that account. |

`create-apikey.sh` and `delete-apikey.sh` also take `POLIS_ENV=local` for the local stack. If several user rows share the e-mail,
the lowest `uid` that has a password is used. Keys and their use by Citizens are covered in
[Connecting an installation](../bridge/setup.md).

## Database changes

PolisOrbis runs its SQL migrations only when the database is first created, and the Postgres image is upstream's. Changes the fork
needs afterwards live in `deploy/sql/*.sql` (idempotent, applied in name order) and are applied with:

```sh
./deploy/prod/migrate.sh                  # POLIS_ENV=local for the local stack
```

Run it after `polis.sh prod up` whenever the changelog mentions a database change. There is one file today,
`001_is_listed.sql`: `ALTER TABLE conversations ADD COLUMN IF NOT EXISTS is_listed BOOLEAN NOT NULL DEFAULT FALSE;`. Running the
script twice is harmless.

## The purge and the data loss of 2 November 2026

PolisOrbis is built for a sandbox. `server/startup.sh` installs a cron job (`PRUNE_SCHEDULE`, default 03:00 daily) that posts to
`/api/v3/prune`, which deletes every conversation not modified for `PRUNE_OLDER_THAN` seconds (default 172800, 48 hours) and the
users left without conversations or votes. It ran unnoticed on polis.democracyroutes.com from 29 October and removed the first
conversations on **2 November**. It was found on 2026-11-04. **No backups existed; the data is not recoverable.**

Since 4 November the job and the route exist only when `PRUNE_ENABLED=true`. Both compose overrides and the generated `.env` set
it to `false`, and the nginx site answers 403 on the route as well. **Never set it to `true` on an installation whose data
matters.** After a server image rebuild the container must log "Prune job off" at start.

## Backups

State of the sources, exactly:

* **No backups exist** for polis.democracyroutes.com. This is why the purge was unrecoverable.
* The Postgres container mounts a volume named `backups` at `/backups`, but nothing in the repository writes to it.
* The next planned step (recorded as open in `docs/decisions.md`): a nightly `pg_dump` into the `backups` volume plus a copy off
  the host. Retention is undecided.

Until that exists, an installation should arrange its own dump of the `polis` database and of the `postgres` volume.

## Upgrading

1. Change the code, commit and push to the GitHub repository (the footer's source link must match what runs).
2. `./deploy/build-images.sh all` (stop the local stack first if it runs).
3. `./deploy/polis.sh prod up`.
4. `./deploy/prod/migrate.sh` if the changelog mentions a database change.
5. Check that the server logs "Prune job off".

## Host limits

From `docs/host.md` (measured 2026-10-28, to be re-measured before relying on it): the shared host has 4 cores and 5.9 GB of RAM
with a 16 GB swap file; memory is the constraint and CPU is idle. Rules for the Polis stacks on it:

* every container gets `--memory` and `--memory-swap`;
* check `free -m` before starting a stack, and stop the local stack when a session ends;
* check `docker ps` and `ss -ltn` before binding a port; ports 80 and 443 belong to the host nginx;
* do not touch the Citizens or Nextcloud containers.

Polis was planned for its own VM; it runs on the shared host by the owner's decision of 2026-10-29.
