# Getting started

This section takes you from a server to a recorded, reviewed and published assembly. Citizens
needs a server that can run Docker containers, and it runs in one of two ways: standalone
with Docker Compose behind your own reverse proxy, or as an ExApp inside a Nextcloud with
AppAPI.

1. Check the [requirements](requirements.md) for both modes.
2. Install, either
    * [with Docker Compose](standalone.md), without Nextcloud, or
    * [as a Nextcloud ExApp](install-nextcloud.md).
3. Follow [First assembly in 15 minutes](first-assembly.md): create a session, print the QR
   sheet, join phones, record, end, review and publish.

Until you add a speech-to-text key and an analysis endpoint in Settings, the app records and
stores audio but sends nothing anywhere. Configure providers in the
[Settings reference](../admin/settings.md) once the app is running.

Citizens is beta software. Rehearse on the actual phones, over the venue's network, before a
high-stakes assembly; the [event checklist](../organizers/before-the-day.md) describes how.
