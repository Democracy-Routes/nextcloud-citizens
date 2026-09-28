#!/bin/sh
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
# Start the built image the way AppAPI starts it and check what AppAPI checks:
# Docker's health verdict and /heartbeat — plus what no unit test can see:
# that a FRESH named volume mounted where AppAPI mounts it is writable, that
# the app runs as uid 10001, that a root-owned volume from an older install is
# repaired, and that HaRP mode (unix socket + frpc) works even while HaRP is
# unreachable, which is the state during AppAPI's own install wait.
#
#   docker build -t citizens-smoke . && sh scripts/image-smoke.sh citizens-smoke
set -eu
IMAGE="${1:-citizens-smoke}"
NAME="citizens-smoke-$$"
VOL="$NAME-data"
STORAGE=/nc_app_citizens_data

cleanup() {
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker volume rm -f "$VOL" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM
fail() {
    echo "FAIL: $*" >&2
    docker logs "$NAME" 2>&1 | tail -60 >&2
    exit 1
}

# Docker's verdict is what AppAPI reads (DockerActions::healthcheckContainer).
wait_healthy() {
    i=0
    while [ $i -lt 90 ]; do
        s=$(docker inspect "$NAME" --format '{{.State.Health.Status}}')
        [ "$s" = healthy ] && return 0
        [ "$s" = unhealthy ] && fail "docker reports unhealthy"
        i=$((i + 1))
        sleep 1
    done
    fail "not healthy after 90 s"
}
# docker top insists on a PID column being present
uid_of() { docker top "$NAME" -eo pid,uid,comm | awk -v c="$1" '$3 == c { print $2; exit }'; }
start() {
    # The environment AppAPI passes. CITIZENS_INSECURE_NO_AUTH only takes
    # effect against a local NEXTCLOUD_URL, which is the point here. Faster
    # probe cadence than the image default, same command.
    docker run -d --name "$NAME" -v "$VOL:$STORAGE" \
        -e APP_ID=citizens -e APP_VERSION=smoke -e APP_SECRET=x \
        -e NEXTCLOUD_URL=http://localhost -e APP_PERSISTENT_STORAGE="$STORAGE" \
        -e APP_HOST=0.0.0.0 -e APP_PORT=23000 -e CITIZENS_INSECURE_NO_AUTH=1 \
        --health-interval=2s --health-timeout=3s --health-start-period=40s --health-retries=5 \
        "$@" "$IMAGE" >/dev/null
}

echo "== 1. docker-install daemon: plain TCP, fresh volume at $STORAGE"
docker volume create "$VOL" >/dev/null
start
wait_healthy
docker exec "$NAME" curl -fsS http://127.0.0.1:23000/heartbeat | grep -q '"status":"ok"' || fail "heartbeat"
health=$(docker exec "$NAME" curl -fsS http://127.0.0.1:23000/api/v1/health)
echo "$health" | grep -q '"storage":"ok"' || fail "storage not ok: $health"
echo "$health" | grep -q '"database":"ok"' || fail "database not ok: $health"
[ "$(uid_of python3)" = 10001 ] || fail "app runs as uid '$(uid_of python3)', want 10001"
for p in "$STORAGE" "$STORAGE/citizens.db"; do
    o=$(docker exec "$NAME" stat -c %u:%g "$p")
    [ "$o" = 10001:10001 ] || fail "$p owned by $o"
done
# HaRP's certificate step and AppAPI's CA injection, exactly as they run
# them: docker exec with no user, i.e. as the image's user.
docker exec "$NAME" mkdir -p /certs/frp || fail "mkdir -p /certs/frp as the image user"
docker exec "$NAME" update-ca-certificates >/dev/null 2>&1 || fail "update-ca-certificates as the image user"
# AppAPI starts, stops and starts the container at install: the entrypoint
# must be idempotent
docker restart "$NAME" >/dev/null
wait_healthy
docker rm -f "$NAME" >/dev/null

echo "== 2. volume kept from an older install, owned by root: must be repaired"
docker run --rm --user root --entrypoint sh -v "$VOL:/v" "$IMAGE" \
    -c 'touch /v/stray && chown -R 0:0 /v'
start
wait_healthy
for p in "$STORAGE" "$STORAGE/stray" "$STORAGE/citizens.db"; do
    o=$(docker exec "$NAME" stat -c %u "$p")
    [ "$o" = 10001 ] || fail "$p still uid $o after the repair"
done
docker rm -f "$NAME" >/dev/null

echo "== 3. HaRP daemon: unix socket + frpc, with HaRP unreachable"
start -e HP_SHARED_KEY=x -e HP_FRP_ADDRESS=127.0.0.1 -e HP_FRP_PORT=7000 -e HP_FRP_DISABLE_TLS=1
wait_healthy
docker exec "$NAME" curl -fsS --unix-socket /tmp/exapp.sock http://localhost/heartbeat \
    | grep -q '"status":"ok"' || fail "heartbeat over /tmp/exapp.sock"
if docker exec "$NAME" curl -s -o /dev/null http://127.0.0.1:23000/heartbeat; then
    fail "TCP listener present in HaRP mode (run_app did not take the socket branch)"
fi
sleep 5 # a few failed frpc login attempts
[ "$(docker inspect "$NAME" --format '{{.State.Status}}')" = running ] || fail "container died"
[ "$(uid_of python3)" = 10001 ] || fail "app not uid 10001 in HaRP mode"
[ "$(uid_of frpc)" = 10001 ] || fail "frpc not running as uid 10001 (got '$(uid_of frpc)')"
[ "$(docker exec "$NAME" stat -c '%a:%u' /run/frpc.toml)" = 600:10001 ] || fail "frpc.toml permissions"
docker exec "$NAME" grep -q 'unixPath = "/tmp/exapp.sock"' /run/frpc.toml || fail "frpc config"
docker exec "$NAME" curl -fsS --unix-socket /tmp/exapp.sock http://localhost/heartbeat >/dev/null \
    || fail "the app stopped answering after frpc's connection failures"
echo "image smoke test passed"
