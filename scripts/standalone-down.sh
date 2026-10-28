#!/bin/sh
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
# Stop standalone Citizens. The data volume is kept.
set -eu
cd "$(dirname "$0")/.."
exec docker compose -f docker-compose.standalone.yml --env-file .env.standalone down
