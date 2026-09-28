#!/bin/sh
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
# Shared development configuration. Sourced by the other scripts.
set -eu

APP_ID="citizens"
APP_NAME="Citizens"
APP_VERSION="0.6.1"
APP_PORT="23000"
CONTAINER="nc_app_citizens"
IMAGE="citizens-dev"
NETWORK="nextcloud_nextcloud-network"
DATA_VOLUME="citizens_data"
NC_CONTAINER="nextcloud"
NEXTCLOUD_URL="https://cloud.democracyinnovators.com"
DAEMON_NAME="manual_install"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SECRET_FILE="$REPO_DIR/.app_secret"

# One stable secret per checkout; shared between the container and the
# AppAPI registration. Never committed (gitignored).
if [ ! -f "$SECRET_FILE" ]; then
    umask 077
    head -c 32 /dev/urandom | base64 | tr -d '=+/\n' > "$SECRET_FILE"
fi
APP_SECRET="$(cat "$SECRET_FILE")"

occ() {
    docker exec -u www-data "$NC_CONTAINER" php occ "$@"
}
