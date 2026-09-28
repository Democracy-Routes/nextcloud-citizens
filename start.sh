#!/bin/sh
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
# Container entrypoint. Runs as root (the image sets no USER) because two
# things have to happen before the app can start as the unprivileged service
# user, and both need root:
#
#  * AppAPI's docker-install mounts a fresh named volume at
#    APP_PERSISTENT_STORAGE (/nc_app_citizens_data, not the image's /data).
#    An empty named volume inherits the ownership of the image directory,
#    which the Dockerfile prepares — but a volume kept from an older install,
#    a bind mount, or a restore done as root is owned by root, and the first
#    write from uid 10001 then fails before logging is even set up: a crash
#    loop with nothing in the log. So the owner is checked and fixed here.
#  * HaRP's certificate step and AppAPI's CA injection `docker exec`
#    `mkdir -p /certs/frp` and `update-ca-certificates` as the image user.
#
# In HaRP mode (HP_SHARED_KEY set — the same switch nc_py_api's run_app uses)
# the app listens on a unix socket and an frpc tunnel exposes it to HaRP; the
# frpc configuration is the one Nextcloud ships in HaRP's exapps_dev/start.sh
# and app-skeleton-python. Everything after the privileged section runs as
# uid/gid 10001. Started already unprivileged (docker run --user, Kubernetes
# runAsUser) the script is a plain exec, as it always was.
set -eu
cd "$(dirname "$0")"

APP_UID=10001
APP_GID=10001
STORAGE="${APP_PERSISTENT_STORAGE:-/data}"
SOCK="${HP_EXAPP_SOCK:-/tmp/exapp.sock}"
FRPC_CONFIG=/run/frpc.toml
FRP_CERTS=/certs/frp

log() { echo "start.sh: $*"; }

as_app() {
    if [ "$(id -u)" -eq 0 ]; then
        setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups "$@"
    else
        "$@"
    fi
}

if [ "$(id -u)" -eq 0 ]; then
    # --- persistent storage: create if missing, fix ownership if wrong ---
    if [ ! -d "$STORAGE" ]; then
        log "creating $STORAGE"
        install -d -o "$APP_UID" -g "$APP_GID" -m 0755 "$STORAGE"
    fi
    if [ "$(stat -c %u "$STORAGE")" != "$APP_UID" ]; then
        # The root directory first (that is what unblocks the app), then only
        # the entries that are actually wrong: a large, correctly owned tree
        # costs one stat per file, not a chown per file.
        log "fixing ownership of $STORAGE (was uid $(stat -c %u "$STORAGE"))"
        chown "$APP_UID:$APP_GID" "$STORAGE" || log "warning: chown $STORAGE failed"
        find "$STORAGE" ! -user "$APP_UID" -exec chown -h "$APP_UID:$APP_GID" {} + \
            || log "warning: recursive ownership fix incomplete"
    fi

    # --- HaRP: socket dir writable, no stale socket, certificates readable ---
    if [ -n "${HP_SHARED_KEY:-}" ]; then
        install -d -m 1777 "$(dirname "$SOCK")"
        # uvicorn cannot always remove a socket left by a previous run (the
        # entrypoint runs twice at install: AppAPI starts and stops the
        # container once for its certificate step)
        rm -f "$SOCK"
        if [ -d "$FRP_CERTS" ]; then
            chown -R "$APP_UID:$APP_GID" "$FRP_CERTS"
            chmod 0600 "$FRP_CERTS"/client.key 2>/dev/null || true
        fi
    fi
    export HOME=/app
fi

# --- HaRP: the frpc tunnel ---
if [ -n "${HP_SHARED_KEY:-}" ]; then
    if [ -z "${HP_FRP_ADDRESS:-}" ] || [ -z "${HP_FRP_PORT:-}" ]; then
        log "warning: HP_SHARED_KEY is set but HP_FRP_ADDRESS/HP_FRP_PORT are not; listening on $SOCK with no tunnel"
    else
        # TLS whenever HaRP delivered client certificates; HP_FRP_DISABLE_TLS
        # is a local-testing override AppAPI never sends.
        case "${HP_FRP_DISABLE_TLS:-}" in
            1|true|TRUE|yes) tls_enable=false ;;
            *) if [ -f "$FRP_CERTS/client.crt" ]; then tls_enable=true; else tls_enable=false; fi ;;
        esac
        # The shared key goes into this file: 0600 and owned by the service
        # user before a single byte is written to it.
        if [ "$(id -u)" -eq 0 ]; then
            install -m 0600 -o "$APP_UID" -g "$APP_GID" /dev/null "$FRPC_CONFIG"
        else
            FRPC_CONFIG=/tmp/frpc.toml
            install -m 0600 /dev/null "$FRPC_CONFIG"
        fi
        {
            echo "serverAddr = \"$HP_FRP_ADDRESS\""
            echo "serverPort = $HP_FRP_PORT"
            echo "loginFailExit = false"
            echo
            echo "transport.tls.enable = $tls_enable"
            if [ "$tls_enable" = true ]; then
                echo "transport.tls.certFile = \"$FRP_CERTS/client.crt\""
                echo "transport.tls.keyFile = \"$FRP_CERTS/client.key\""
                echo "transport.tls.trustedCaFile = \"$FRP_CERTS/ca.crt\""
                echo "transport.tls.serverName = \"harp.nc\""
            fi
            echo
            echo "metadatas.token = \"$HP_SHARED_KEY\""
            echo
            echo "[[proxies]]"
            echo "remotePort = ${APP_PORT:-23000}"
            echo "type = \"tcp\""
            echo "name = \"${APP_ID:-citizens}\""
            echo "[proxies.plugin]"
            echo "type = \"unix_domain_socket\""
            echo "unixPath = \"$SOCK\""
        } > "$FRPC_CONFIG"
        log "HaRP mode: frpc -> $HP_FRP_ADDRESS:$HP_FRP_PORT (tls=$tls_enable), app on $SOCK"
        # loginFailExit = false: frpc keeps retrying and never takes the app down
        as_app frpc -c "$FRPC_CONFIG" &
    fi
fi

# exec takes a command, not a shell function: spell the two cases out so the
# app is PID 1 either way and receives Docker's SIGTERM directly
if [ "$(id -u)" -eq 0 ]; then
    exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups python3 -m citizens.main
fi
exec python3 -m citizens.main
