#!/bin/sh
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
# Docker HEALTHCHECK. AppAPI reads Docker's verdict before it enables an
# ExApp (DockerActions::healthcheckContainer): "unhealthy" aborts the
# install. nc_py_api's run_app listens on a unix socket whenever
# HP_SHARED_KEY is set, so the probe has to follow the same switch — a TCP
# probe in that mode reported the container unhealthy while it worked.
set -u
if [ -n "${HP_SHARED_KEY:-}" ]; then
    # frpc dying means HaRP can no longer reach us: that is an outage, say so
    if [ -n "${HP_FRP_ADDRESS:-}" ]; then
        alive=0
        for c in /proc/[0-9]*/comm; do
            if read -r name < "$c" 2>/dev/null && [ "$name" = frpc ]; then
                alive=1
                break
            fi
        done
        [ "$alive" -eq 1 ] || exit 1
    fi
    exec curl -fsS --max-time 4 --unix-socket "${HP_EXAPP_SOCK:-/tmp/exapp.sock}" \
        http://localhost/heartbeat >/dev/null
fi
exec curl -fsS --max-time 4 "http://127.0.0.1:${APP_PORT:-23000}/heartbeat" >/dev/null
