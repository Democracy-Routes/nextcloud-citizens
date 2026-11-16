# Install as a Nextcloud ExApp

This page installs Citizens in a Nextcloud, which runs it as a container next to itself and
talks to it through the AppAPI proxy. To run without Nextcloud, see
[Install with Docker Compose](standalone.md).

## From the App Store

Settings, Administration, **External Apps**, find *Citizens* and press **Install**. AppAPI pulls
`ghcr.io/democracy-routes/citizens`, starts it, and enables it. The app then appears in
the top menu for every user.

## From the image, on the command line

Use this for an instance that installs apps by hand, or a version the store does not
carry yet. `occ` runs inside your Nextcloud container
(`docker exec -u www-data <nextcloud> php occ ...`).

1. Register a deploy daemon, if there is none yet. For example, a Docker Socket Proxy daemon on
   the same host:

    ```sh
    occ app_api:daemon:register docker_local "Docker (local)" docker-install \
        http nextcloud-appapi-dsp:2375 https://cloud.example.org --net nextcloud
    ```

    The last URL is the address the app container uses to reach Nextcloud; the app
    also reads `overwrite.cli.url` for the phones, so an internal address here is fine.
    `--net` is the Docker network the Nextcloud container is on. HaRP daemons take
    `--harp ...` options; follow the AppAPI documentation for the daemon itself.

2. Register the app from its `info.xml`: a local path readable by the Nextcloud
   container, or the raw file from the tag you are installing:

    ```sh
    occ app_api:app:register citizens docker_local --wait-finish \
        --info-xml https://raw.githubusercontent.com/Democracy-Routes/nextcloud-citizens/v0.6.2/appinfo/info.xml
    ```

    AppAPI pulls `ghcr.io/democracy-routes/citizens:<version>` (the `<image-tag>` in that
    file), creates the container `nc_app_citizens` and the volume `nc_app_citizens_data`,
    starts it, waits for `/heartbeat`, and enables it. `--wait-finish` returns when the app
    is enabled or prints why it is not. Replace the tag in the URL with the version you
    want to install.

3. Give the container memory. AppAPI sets no limit unless the daemon has resource
   limits configured in the UI:

    ```sh
    docker update --memory 2g --memory-swap 2g nc_app_citizens
    ```

4. Check the result:
    * `occ app_api:app:list` shows `citizens <version> [enabled]`.
    * `docker inspect nc_app_citizens --format '{{.State.Health.Status}}'` says `healthy`.
    * The *Citizens* entry is in the top menu.
    * `docker logs nc_app_citizens` shows `app_started` and a `public_url_resolved` line
      with the address the QR codes will carry.

## Public address { #public-address }

The phones open `<public address>/index.php/apps/app_api/proxy/citizens/recorder.html`.
The app asks Nextcloud for `overwrite.cli.url` and uses that; when it is unset it falls
back to the daemon's Nextcloud URL, which may be an internal name. To pin it, pass the
address at registration:

```sh
occ app_api:app:register citizens docker_local --wait-finish --info-xml ... \
    --env CITIZENS_PUBLIC_URL=https://cloud.example.org
```

The same option accepts `CITIZENS_JOB_WORKERS` (default 10; `1` runs transcriptions and
analyzes one at a time) and `CITIZENS_LOG_LEVEL`.

## The secret

AppAPI generates the app secret and keeps it in its own database and in the container's
environment (`docker inspect nc_app_citizens`); nothing on disk needs it.
`scripts/event-status.sh` and `scripts/backup-citizens-data.sh` find the AppAPI-created
volume by themselves.

## Hand-run container (manual-install daemon)

The development instance and the first event instance run this way. The container is built
and started by `scripts/event-up.sh` from a checkout and registered with a *manual-install*
daemon whose host is the container's name (see `scripts/register.sh` and the
[development environment](../contributing/development-environment.md)). AppAPI then pulls
nothing and manages nothing; you do, with those scripts. See
[Updates and releases](../admin/updates.md) for the frozen-image flow.

## What happens next

Without API keys the app records and stores audio but performs no transcription and no
analysis. Open **Citizens, Settings**, which only Nextcloud administrators see, and follow
the [Settings reference](../admin/settings.md). Then continue with [First assembly in 15 minutes](first-assembly.md).

The AppAPI proxy forwards GET, POST, PUT and DELETE only, caps a request body at a few
megabytes, and authenticates with the Nextcloud session. See
[Architecture](../architecture/index.md) for the consequences.
