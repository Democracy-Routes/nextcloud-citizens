#!/bin/sh
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
# Start/stop/seed a throwaway Citizens instance for Playwright browser tests.
# Runs WITHOUT AppAPI auth on 127.0.0.1:23100 with an ephemeral data volume.
set -eu
. "$(dirname "$0")/dev-env.sh"

TEST_CONTAINER="citizens-browser-test"
TEST_PORT="23100"

case "${1:-}" in
    start)
        docker build -q -t "$IMAGE" "$REPO_DIR" >/dev/null
        docker rm -f "$TEST_CONTAINER" >/dev/null 2>&1 || true
        docker run -d \
            --name "$TEST_CONTAINER" \
            -p "127.0.0.1:$TEST_PORT:23000" \
            --memory 512m --memory-swap 512m \
            -v "$REPO_DIR":/app \
            -e APP_ID=citizens -e APP_VERSION=test -e APP_HOST=0.0.0.0 -e APP_PORT=23000 \
            -e APP_SECRET=browser-test -e NEXTCLOUD_URL=http://localhost \
            -e APP_PERSISTENT_STORAGE=/tmp/citizens-test-data \
            -e CITIZENS_INSECURE_NO_AUTH=1 \
            --entrypoint sh "$IMAGE" \
            -c "cd /app && exec python3 -m uvicorn citizens.main:APP --host 0.0.0.0 --port 23000" \
            >/dev/null
        for _ in $(seq 1 30); do
            if curl -sf -o /dev/null "http://127.0.0.1:$TEST_PORT/recorder"; then
                echo "ready on http://127.0.0.1:$TEST_PORT"
                exit 0
            fi
            sleep 1
        done
        echo "test instance failed to start" >&2
        docker logs "$TEST_CONTAINER" | tail -20 >&2
        exit 1
        ;;
    seed)
        docker exec -e APP_PERSISTENT_STORAGE=/tmp/citizens-test-data "$TEST_CONTAINER" \
            sh -c "cd /app && python3 -m citizens.devtools seed-recorder-test"
        ;;
    seed-load)
        # one assembly with N tables (default 10) — see tests/load/load_g_single_assembly.py
        docker exec -e APP_PERSISTENT_STORAGE=/tmp/citizens-test-data "$TEST_CONTAINER" \
            sh -c "cd /app && python3 -m citizens.devtools seed-load-test ${2:-10}"
        ;;
    api)
        # organizer API call from inside the container — see citizens.devtools
        shift
        docker exec -e APP_PERSISTENT_STORAGE=/tmp/citizens-test-data "$TEST_CONTAINER" \
            python3 -m citizens.devtools api "$@"
        ;;
    stop)
        docker rm -f "$TEST_CONTAINER" >/dev/null 2>&1 || true
        echo "stopped"
        ;;
    *)
        echo "Usage: $0 start|seed|seed-load [N]|api METHOD PATH [JSON]|stop" >&2
        exit 2
        ;;
esac
