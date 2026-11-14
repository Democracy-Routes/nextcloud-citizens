# Getting started

Citizens needs a server that can run Docker containers, and one of two hosts: a
Nextcloud with AppAPI, or your own reverse proxy in front of the standalone container.
Pick one, then run a first assembly to see the whole flow.

1. [Requirements](requirements.md) for both modes.
2. Install, either
    * [as a Nextcloud ExApp](install-nextcloud.md), or
    * [standalone](standalone.md), without Nextcloud.
3. [First assembly in 15 minutes](first-assembly.md): create a session, print the QR
   sheet, join phones, record, end, review and publish.

Until you add a speech-to-text key and an analysis endpoint in Settings, the app
records and stores audio but sends nothing anywhere. Configure providers in the
[Settings reference](../admin/settings.md) once the app is running.

!!! info "Beta software"
    Rehearse on the actual phones, over the venue's network, before a high-stakes
    assembly. The [event checklist](../organizers/before-the-day.md) describes how.
