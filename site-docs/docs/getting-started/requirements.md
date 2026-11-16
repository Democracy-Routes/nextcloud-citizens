# Requirements

This page lists what the server, the network and the phones need. Requirements shared by both
install modes come first, then those specific to one mode.

## Common to both modes

* Docker, able to run the Citizens image (`ghcr.io/democracy-routes/citizens`).
* Disk for audio. Recordings take roughly 10 MB per table per hour, plus the assembled
  copy. Unfinished upload parts are not expired automatically and use disk until a recording
  is assembled, so leave headroom.
* HTTPS. Phones will not record over plain HTTP, so the address people scan must be served
  over HTTPS.
* Memory. A container needs enough memory for a real assembly. Ten tables peak near 500 MiB
  while transcribing, and the event scripts give the container 2 GiB. Large Vosk models need
  more (see below).

## Docker Compose (standalone)

* A server or VM with Docker and the Docker Compose plugin.
* Memory and CPU:
    * 4 GB RAM and 2 vCPU for cloud speech-to-text or small Vosk models.
    * 8 GB RAM and 4 vCPU with large Vosk models. Set `mem_limit` and `memswap_limit` in
      `docker-compose.standalone.yml` to `6g`.
* 20 GB of disk, plus about 2 GB for each large Vosk model.
* A domain name, for example `citizens.example.org`, and a reverse proxy that serves it over
  HTTPS.
* Optional: an SMTP server for invitation and reset mails.

## Nextcloud ExApp

* Nextcloud 32 or newer.
* The AppAPI app enabled, with a deploy daemon configured (Settings, Administration,
  External Apps, Deploy daemons). Both daemon kinds work: the classic Docker Socket Proxy
  and HaRP. The app ships the `frpc` client that HaRP needs and switches to it by itself.
* `overwrite.cli.url` set to the public address of your Nextcloud
  (`occ config:system:get overwrite.cli.url`). The QR codes the tables scan are built on it.
  If it cannot be set, pin the address with `CITIZENS_PUBLIC_URL` at registration; see
  [Install as a Nextcloud ExApp](install-nextcloud.md#public-address).

## Providers

No provider is required to install. To get transcripts and findings, configure these in
Settings:

* a speech-to-text engine: a key for Deepgram or Mistral, an OpenAI-compatible Whisper
  endpoint, or Vosk (a server of your own, or the built-in engine with models installed from
  Settings);
* an analysis endpoint: any OpenAI-compatible service, including a self-hosted one.

[Providers and egress](../admin/providers-egress.md) describes what each choice sends where.

## Phones

Table phones need a current browser and a microphone permission for the site. The recorder
asks the browser to keep the screen awake, but a phone can override that;
[Before the day](../organizers/before-the-day.md) lists the settings to change on iPhone and
Android. Only Chromium reports battery level and storage, so a table showing nothing there is
unknown rather than fine.
