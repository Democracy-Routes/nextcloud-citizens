# Backups and restore

The app keeps everything in its persistent volume: the SQLite database, audio, transcripts, live
captions and logs.

| Install | Volume | Mount |
|---|---|---|
| AppAPI-managed | `nc_app_citizens_data` | `/nc_app_citizens_data` |
| Hand-run container | `citizens_data` | `/data` |
| Standalone | `citizens_standalone_data` (Compose prefixes the project name) | `/data` |

Back that volume up together with Nextcloud itself. The scripts pick whichever exists.

## Taking a backup

`scripts/backup-citizens-data.sh` takes a consistent snapshot while the app runs: `VACUUM INTO` copies
the database as one transaction (WAL mode makes this safe), the rest of the volume is tarred, and both
are checksummed into `/root/backups/citizens-data-<timestamp>/`. In standalone mode pass the real volume
name as the first argument. The host needs `sqlite3`.

Set `BACKUP_ROOT` to change the destination and `CITIZENS_BACKUP_REMOTE` to an rsync target to copy it
off the host. A snapshot on the same disk as the data protects against mistakes, not against the disk.

Install it nightly:

```sh
install -m 755 scripts/backup-citizens-data.sh /usr/local/sbin/citizens-backup
( crontab -l 2>/dev/null; echo '30 2 * * * /usr/local/sbin/citizens-backup >> /var/log/citizens-backup.log 2>&1' ) | crontab -
```

A snapshot taken while a recording is uploading may miss its most recent chunks; the phone still holds
them and re-sends on reconnect.

!!! danger "Standalone: keep `.env.standalone`"
    Without `APP_SECRET` the stored API keys cannot be read. Back the file up with the volume.

## Restore

Rehearse it once on a throwaway volume before you need it.

```sh
docker volume create citizens_restore
docker run --rm -v citizens_restore:/data -v /root/backups/citizens-data-<stamp>:/in:ro alpine sh -c \
  'tar xzf /in/citizens_data-files.tar.gz -C /data && cp /in/citizens.db /data/citizens.db && chown -R 10001:10001 /data'
sqlite3 "file:$(docker volume inspect citizens_restore --format '{{.Mountpoint}}')/citizens.db?mode=ro" \
  'select count(*) from assemblies; select count(*) from recordings; select version_num from alembic_version'
```

To restore for real, stop the container, repeat the same into the live volume (or point the container at
the restored volume), and start it. Migrations run at startup, so a snapshot from an older version
upgrades itself. Ownership is repaired at start as well: the entrypoint hands the volume to the service
user (uid 10001) if a restore left it owned by root.

## Rehearse the schema round-trip too

A backup and a migration path nobody has exercised together are each only half rehearsed. After
restoring into `citizens_restore`, check that a downgrade and a re-upgrade leave the data alone. See
[Updates and releases](updates.md#rolling-back) for the commands, then compare the row counts: they must
be identical.

## Before an event

Take a snapshot, restore it into a throwaway volume and count the assemblies. See
[Before the day](../organizers/before-the-day.md).
