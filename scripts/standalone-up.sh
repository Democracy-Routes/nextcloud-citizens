#!/bin/sh
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
# Build and start Citizens in standalone mode, then wait until it answers.
#
#   cp .env.standalone.example .env.standalone   # edit it first
#   sh scripts/standalone-up.sh
#
# Run it again after `git pull` to update. Guide: docs/standalone.md
set -eu
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

if [ ! -f .env.standalone ]; then
    echo "Missing .env.standalone. Copy .env.standalone.example and edit it." >&2
    exit 1
fi

# the port may be set in the environment or in the env file
PORT="${CITIZENS_PORT:-}"
if [ -z "$PORT" ]; then
    PORT="$(sed -n 's/^CITIZENS_PORT=//p' .env.standalone | tail -n 1)"
fi
PORT="${PORT:-23000}"
export CITIZENS_PORT="$PORT"

COMPOSE="docker compose -f docker-compose.standalone.yml --env-file .env.standalone"
$COMPOSE up -d --build

echo "Waiting for http://127.0.0.1:$PORT/heartbeat ..."
i=0
while [ "$i" -lt 60 ]; do
    if curl -fsS --max-time 3 "http://127.0.0.1:$PORT/heartbeat" >/dev/null 2>&1; then
        echo "Citizens is up."
        $COMPOSE ps
        exit 0
    fi
    i=$((i + 1))
    sleep 2
done
echo "Citizens did not answer within two minutes. Last log lines:" >&2
$COMPOSE logs --tail 40 citizens >&2 || true
exit 1
