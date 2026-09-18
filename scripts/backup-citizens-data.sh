#!/bin/sh
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
# Snapshot the citizens_data volume: a consistent copy of the SQLite database
# (VACUUM INTO reads a transaction-consistent image while the app keeps
# writing) plus a tarball of the audio, transcripts, captions and logs.
# Every recording, transcript and finding lived in one copy on one disk
# until this existed.
#
#   sh scripts/backup-citizens-data.sh                 # into /root/backups
#   BACKUP_ROOT=/mnt/x CITIZENS_BACKUP_REMOTE=user@host:/backups/citizens sh scripts/backup-citizens-data.sh
#
# Restore: docs/administration.md § Backups.
set -eu
VOLUME="${VOLUME:-citizens_data}"
BACKUP_ROOT="${BACKUP_ROOT:-/root/backups}"
BACKUP_KEEP="${BACKUP_KEEP:-14}"
REMOTE="${CITIZENS_BACKUP_REMOTE:-}"
VOLUME_DIR="$(docker volume inspect "$VOLUME" --format '{{.Mountpoint}}')"
DB="$VOLUME_DIR/citizens.db"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
DEST="$BACKUP_ROOT/citizens-data-$STAMP"
mkdir -p "$DEST"

sqlite3 "file:$DB?mode=ro" "VACUUM INTO '$DEST/citizens.db'"
sqlite3 "file:$DEST/citizens.db?mode=ro" "pragma integrity_check" | grep -qx ok
# exports are throwaway archives and temp is in-flight work; the db is above
docker run --rm -v "$VOLUME":/data:ro -v "$DEST":/out alpine \
    tar czf /out/citizens_data-files.tar.gz -C /data \
        --exclude='./citizens.db' --exclude='./citizens.db-wal' --exclude='./citizens.db-shm' \
        --exclude='./temp' --exclude='./exports' .
(cd "$DEST" && sha256sum citizens.db citizens_data-files.tar.gz > SHA256SUMS)
echo "snapshot: $DEST ($(du -sh "$DEST" | cut -f1))"

if [ -n "$REMOTE" ]; then
    rsync -a "$DEST" "$REMOTE/" && echo "copied to $REMOTE"
else
    echo "no CITIZENS_BACKUP_REMOTE set: this copy is on the same disk as the data"
fi

# keep the newest BACKUP_KEEP snapshots
ls -1d "$BACKUP_ROOT"/citizens-data-* 2>/dev/null | sort | head -n "-$BACKUP_KEEP" | while read -r old; do
    rm -rf "$old" && echo "pruned $old"
done
