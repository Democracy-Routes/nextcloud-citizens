#!/bin/sh
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
# Freeze the app for an event: build an immutable image from THIS checkout and
# run it in place of the dev container — same name, network, data volume and
# environment as dev-up.sh, but with no source bind mount and no --reload
# (a saved file cannot restart the server mid-round), 2 GiB (ten tables peak
# near 500 MiB while transcribing) and INFO logs (a day fits in the files).
#
#   sh scripts/event-up.sh            # from the checkout to freeze
#   CITIZENS_JOB_WORKERS=1 sh scripts/event-up.sh   # strictly sequential jobs, as before
#
# The AppAPI registration is untouched: Nextcloud still reaches the container
# by name. Undo with scripts/dev-up.sh after the event.
set -eu
. "$(dirname "$0")/dev-env.sh"

SHA="$(git -C "$REPO_DIR" rev-parse --short HEAD)"
if [ -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no)" ]; then
    echo "The checkout has uncommitted changes; freeze a commit, not a working tree." >&2
    exit 1
fi
EVENT_IMAGE="citizens-event:$SHA"

echo "Building $EVENT_IMAGE from $REPO_DIR …"
docker build -q -t "$EVENT_IMAGE" "$REPO_DIR" >/dev/null
docker volume create "$DATA_VOLUME" >/dev/null
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d \
    --name "$CONTAINER" \
    --network "$NETWORK" \
    --restart unless-stopped \
    --memory 2g --memory-swap 2g \
    -v "$DATA_VOLUME":/data \
    -e APP_ID="$APP_ID" \
    -e APP_VERSION="$APP_VERSION" \
    -e APP_HOST=0.0.0.0 \
    -e APP_PORT="$APP_PORT" \
    -e APP_SECRET="$APP_SECRET" \
    -e NEXTCLOUD_URL="$NEXTCLOUD_URL" \
    -e APP_PERSISTENT_STORAGE=/data \
    -e CITIZENS_JOB_WORKERS="${CITIZENS_JOB_WORKERS:-10}" \
    -e CITIZENS_LOG_LEVEL=INFO \
    "$EVENT_IMAGE" \
    >/dev/null

# say what is actually running, so the freeze can be checked by eye
docker inspect "$CONTAINER" --format \
    'running {{.Config.Image}}  memory={{.HostConfig.Memory}}  mounts={{len .Mounts}}  cmd={{json .Config.Cmd}}  entrypoint={{json .Config.Entrypoint}}'
echo "Frozen at $SHA. Next: occ app_api:app:list, open the UI, then"
echo "  python3 tests/load/load_h_realtime_assembly.py --smoke"
