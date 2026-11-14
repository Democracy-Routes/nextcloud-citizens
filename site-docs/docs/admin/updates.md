# Updates and releases

## How upgrades work

Migrations run automatically, forward only, at every startup (`citizens/db/migrate.py`, called from
`main.py` on every boot): the container upgrades its database to `head` before it answers requests. There
is no automatic downgrade; rolling back the schema is a deliberate, by-hand step (below). Migrations are
additive; see [Database and migrations](../architecture/database.md).

## Updating an instance

1. **Back up first:** `scripts/backup-citizens-data.sh`. See [Backups and restore](backups.md).
2. Update:
    * **AppAPI-managed install:** re-run `occ app_api:app:register citizens <daemon> --wait-finish
      --info-xml <url to the new tag's info.xml>`. AppAPI pulls the new image, replaces the container,
      and the container's own startup runs the migrations.
    * **Hand-run install:** pull the new commit or tag and run `scripts/event-up.sh` again. It refuses a
      dirty checkout: commit or stash first.
    * **Standalone:** `git pull` then `sh scripts/standalone-up.sh`.
3. **Confirm:** `occ app_api:app:list` shows the new version, and `GET /api/v1/health` reports a healthy
   database.

## Rolling back { #rolling-back }

Re-register (AppAPI-managed) or check out (hand-run) the *previous* tag's `info.xml` or commit the same
way, then downgrade the schema to match it. The app never runs a downgrade, so invoke Alembic directly
against the volume with the *old* image, which carries the matching migration scripts. For example, to go
back before migrations `0037` and `0038`, downgrade to `0036`:

```sh
docker run --rm -v <data-volume>:/data --entrypoint python3 \
  ghcr.io/democracy-routes/citizens:<previous-version> -c "
from alembic import command
from alembic.config import Config
cfg = Config()
cfg.set_main_option('script_location', 'citizens/db/migrations')
cfg.set_main_option('sqlalchemy.url', 'sqlite:////data/citizens.db')
command.downgrade(cfg, '0036')"
```

Then start the old image. Going forward again later just means starting the new image once more; its own
startup runs `upgrade head`. Use the revision that precedes the first migration you want to undo; the
administration guide's `0036` example is for the 0.7 Block 2 pair.

To rehearse the round-trip, run the downgrade and then `command.upgrade(cfg, 'head')` against a restored
copy and compare row counts before and after.

## The frozen image for an event

A development container runs the checkout with auto-reload, which is dangerous during an event. For a
hand-run install, `scripts/event-up.sh` freezes the app:

```sh
sh scripts/event-up.sh                      # from the checkout to freeze
CITIZENS_JOB_WORKERS=1 sh scripts/event-up.sh   # strictly sequential jobs
```

It builds an immutable image `citizens-event:<short commit>` from the checkout (it refuses a checkout
with uncommitted changes: freeze a commit, not a working tree) and runs it in place of the dev container,
with the same name, network, data volume and environment, but no source bind mount, no `--reload`,
2 GiB of memory and INFO logs. The AppAPI registration is untouched; Nextcloud still reaches the container
by name. Undo it with `scripts/dev-up.sh` after the event. For built-in Vosk, use
`CITIZENS_VOSK_BUILTIN=1` (memory 3500m, optionally `CITIZENS_MEMORY=6g`).

After freezing, confirm `occ app_api:app:list` still shows the app enabled, then run
`python3 tests/load/load_h_realtime_assembly.py --smoke`. Never run `make up` or `scripts/dev-up.sh` on the
day. An AppAPI-installed container already runs the tagged image with no bind mount.

## Releasing to the Nextcloud App Store

Citizens is an ExApp: the App Store hosts only metadata, and the code ships as the Docker image named in
`appinfo/info.xml` under `<docker-install>`. A release has two artefacts: a published image and a signed
metadata archive.

### One-time setup

1. **App Store account and token** at apps.nextcloud.com (register or sign in with GitHub, then create an
   API token; GitHub accounts have no password, so the token is the only way to authenticate).
2. **Code-signing certificate.** The key's CN must equal the app id (`citizens`). Open a pull request
   against `nextcloud/app-certificate-requests` adding `citizens/citizens.csr`; maintainers commit
   `citizens/citizens.crt` on merge. Start this first: it is the only step that waits on other people.
   Never commit the key (`*.key` is gitignored).
3. **Register the app id** with the certificate and a signature of the app id, using the API or the
   developer form.
4. **GitHub repository secrets:** `APP_PRIVATE_KEY` (the key), `APP_PUBLIC_CRT` (the certificate) and
   `APPSTORE_TOKEN`. The image is pushed to GHCR with the workflow's own `GITHUB_TOKEN`; make the package
   public after the first push, because AppAPI pulls anonymously.

!!! danger "Re-issuing a certificate deletes every existing release"
    All previous signatures become invalid. Keep the key safe and backed up.

### Every release

```sh
make version VERSION=0.6.0-beta.1   # all six declarations at once
make appstore-check                 # validates info.xml the way the store does
make lint && make test
cd frontend && npm run build && cd ..   # bundles ship in the image; CI checks them
git commit -am "Release 0.6.0-beta.1" && git tag v0.6.0-beta.1
git push origin main --tags
```

Pushing the tag runs `.github/workflows/release.yml`, which checks the tag matches `<version>` in
`info.xml` and builds and pushes `ghcr.io/democracy-routes/citizens` for **amd64 and arm64**. The App Store
step is separate and on demand (Actions, Release, *Run workflow* on the tag, with *publish* ticked): it
packages `build/citizens.tar.gz` (metadata only), signs it, attaches it to the GitHub release and
publishes it. A version containing `-beta` or `-alpha` is flagged as a pre-release on the store.

### What the image guarantees to AppAPI

`scripts/image-smoke.sh` runs in CI against the production image: started with the environment AppAPI
passes, on a fresh named volume at `/nc_app_citizens_data`, the container goes healthy, `/heartbeat` and
`/api/v1/health` answer, the app runs as uid 10001 and owns the volume, and a volume left owned by root is
repaired at start. In HaRP mode (`HP_SHARED_KEY` set) the app listens on `/tmp/exapp.sock` and `frpc` runs as
uid 10001 with a 0600 configuration. The smoke test cannot replace a real HaRP daemon: before relying on a
HaRP install, register the image on a scratch instance with one.

### Release checklist

* `make appstore-check` passes.
* `make lint && make test` pass, bundles rebuilt and committed.
* Screenshots in `img/screenshots/` still reflect the UI.
* `CHANGELOG.md` has a section for this version.
* Tag matches `<version>` and `<image-tag>`.
* The image is public on GHCR and has both architectures.
