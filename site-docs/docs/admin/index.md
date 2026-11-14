# Administration

This section is for the person who installs Citizens, gives it the keys it needs and keeps it
running. The operator's reference is the repository's `docs/administration.md`; these pages
reorganise it by task.

| Task | Page |
|---|---|
| Configure transcription, analysis, organisation data, retention | [Settings reference](settings.md) |
| Understand what each provider receives | [Providers and egress](providers-egress.md) |
| Take a backup, restore, rehearse a restore | [Backups and restore](backups.md) |
| Upgrade, roll back, freeze an image for an event, release | [Updates and releases](updates.md) |
| See what the app is doing | [Monitoring and logs](monitoring.md) |
| Diagnose something that went wrong | [Troubleshooting](troubleshooting.md) |

Installing is covered under Getting started:
[Nextcloud ExApp](../getting-started/install-nextcloud.md) or
[standalone](../getting-started/standalone.md).

## Who can reach Settings

In Nextcloud mode, **Citizens, Settings** is visible to Nextcloud administrators only, checked both by
the AppAPI proxy and by the app. Organizer data is scoped to the Nextcloud user who created the
assembly. In standalone mode, administrators are accounts in the app and manage organizers under
Settings, Organisation, Users.

## What the app stores

Everything lives in the app's persistent storage (mounted at `/data`): the SQLite database, audio,
transcripts, live captions and logs. Citizens never reads or writes Nextcloud user files. The full
layout and the retention rules are in the [data map](../privacy/index.md).

## Nothing happens without a provider

A fresh install performs no transcription and no analysis. Until an administrator configures a
provider, the app records and stores audio but sends nothing anywhere.
