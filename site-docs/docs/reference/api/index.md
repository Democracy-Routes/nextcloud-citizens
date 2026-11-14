# API reference

Generated from the application's own OpenAPI document (app version `0.1.0`, 174 operations). Do not edit these pages by hand: rebuild them with `sh scripts/docs-build.sh`.

All organizer routes live under `/api/v1/`. In Nextcloud mode they are reached through the AppAPI proxy at `/index.php/apps/app_api/proxy/citizens/api/v1/...` with a Nextcloud session; in standalone mode they are served at `/api/v1/...` with the sign-in cookie. There is no API token for external services; see [Polis bridge contract](../../bridge/contract.md) for how the one external integration works.

!!! note "Verbs"
    The AppAPI proxy forwards only GET, POST, PUT and DELETE. Partial updates therefore use PUT; the application has no PATCH routes.

| Group | Operations | What it holds |
|---|---|---|
| [Assemblies](assemblies.md) | 56 | Assemblies, their settings, participants, tables, consent, files, report, seeds and everything else scoped to one assembly. Organizer routes. |
| [Rounds (sessions)](rounds.md) | 20 | A Session is a Round in the schema: these routes start and end it, monitor it, and hold its findings, analysis and messages. Organizer routes. |
| [Recordings](recordings.md) | 12 | Operations on one recording: transcripts, audio, retranscription, handover and promotion. Organizer routes. |
| [Sessions](sessions.md) | 5 | Create and list Sessions (including Record now). Organizer routes. |
| [Uploads](uploads.md) | 4 | Resumable uploads in parts, used by session import and by attaching audio or a transcript. Organizer routes. |
| [Administration](admin.md) | 13 | Settings, provider tests, Vosk models and instance status. Administrator routes. |
| [Recorder and participant (public)](recorder.md) | 48 | The routes phones and participants call, authenticated by the bearer token of their session rather than by an organizer sign-in. |
| [Accounts (standalone)](auth.md) | 7 | Sign-in, invitations and password reset in standalone mode. |
| [Other](other.md) | 9 | Health, findings, participants, help requests and the static entry points. |
