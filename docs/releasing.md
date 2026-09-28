# Releasing to the Nextcloud App Store

Citizens is an ExApp: the App Store hosts only **metadata**, and the code ships
as the Docker image named in `appinfo/info.xml` under `<docker-install>`. A
release therefore has two artefacts — a published image and a signed metadata
archive.

## One-time setup

### 1. App Store account and token

Register (or sign in with GitHub) at <https://apps.nextcloud.com/account/register>,
then create an API token at <https://apps.nextcloud.com/account/token>.
Accounts created through GitHub have no password, so the token is the only way
to authenticate.

### 2. Code-signing certificate

The key already exists on the dev server at
`/root/.nextcloud/certificates/citizens.key` with its request next to it
(`citizens.csr`, subject `CN=citizens` — the CN **must** equal the app id).
**Never commit the key**; `*.key` is gitignored.

Open a pull request against
<https://github.com/nextcloud/app-certificate-requests> adding a single file:

```
citizens/citizens.csr
```

Entirely doable in the browser — start at
<https://github.com/nextcloud/app-certificate-requests/new/master>, name the file
`citizens/citizens.csr`, and paste the PEM from
`/root/.nextcloud/certificates/citizens.csr`. Their README asks for a link to
the source, so include
<https://github.com/Democracy-Routes/nextcloud-citizens> in the PR body. Do not
@-mention anyone; the people who can help watch the repo.

**Start this before anything else in this document.** It is the only step that
waits on other people, and every later step — registering the app id, the
release secrets, the first published archive — depends on it. Make sure your GitHub profile shows an email
address. Turnaround is usually a few hours to three days; on merge, maintainers
commit `citizens/citizens.crt` — that is the public certificate.

> Re-issuing a certificate later **deletes every existing release**, because all
> previous signatures become invalid. Keep this key safe and backed up.

### 3. Register the app id

Once the certificate is merged:

```sh
CERT=$(cat citizens.crt)
SIGNATURE=$(echo -n "citizens" \
  | openssl dgst -sha512 -sign /root/.nextcloud/certificates/citizens.key \
  | openssl base64 -A)

curl -X POST https://apps.nextcloud.com/api/v1/apps \
  -H "Authorization: Token $APPSTORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg c "$CERT" --arg s "$SIGNATURE" '{certificate:$c, signature:$s}')"
```

(Or use the form at <https://apps.nextcloud.com/developer/apps/new>.)

### 4. GitHub repository secrets

| Secret | Value |
|---|---|
| `APP_PRIVATE_KEY` | contents of `citizens.key` |
| `APP_PUBLIC_CRT` | contents of `citizens.crt` |
| `APPSTORE_TOKEN` | the API token from step 1 |

The image is pushed to GHCR with the workflow's own `GITHUB_TOKEN`; make the
package public after the first push (Packages → citizens → Package settings).

## Every release

```sh
make version VERSION=0.6.0-beta.1   # all six declarations at once
make appstore-check                 # validates info.xml the way the store does
make lint && make test
cd frontend && npm run build && cd ..   # bundles ship in the image; CI checks them
git commit -am "Release 0.6.0-beta.1" && git tag v0.6.0-beta.1
git push origin main --tags
```

Pushing the tag runs `.github/workflows/release.yml`, which:

1. checks the tag matches `<version>` in `info.xml`;
2. builds and pushes `ghcr.io/democracy-routes/citizens` for **amd64 and arm64**.

That is all a tag does. After the **first** push, open the package on GitHub
(Organization → Packages → citizens → Package settings) and set its
visibility to **Public**: AppAPI pulls anonymously, and a new package is
private by default. From then on the image can be installed on any Nextcloud
with `occ app_api:app:register citizens <daemon> --info-xml …`
(docs/administration.md § 2).

The App Store step is separate and on demand — Actions → Release → *Run
workflow* on the tag, with *publish* ticked. It:

3. packages `build/citizens.tar.gz` (metadata only, one top-level `citizens/`
   folder, well under the store's 20 MB limit);
4. signs it with `APP_PRIVATE_KEY`, attaches it to the GitHub release;
5. publishes it to apps.nextcloud.com.

A version containing `-beta` / `-alpha` is flagged as a **pre-release** on the
store. (A `nightly: true` release is a different mechanism — it replaces the
previous nightly each time; we do not use it.)

## What the image guarantees to AppAPI

`scripts/image-smoke.sh` runs in CI against the production image and is the
contract: started with the environment AppAPI passes, on a fresh named volume
at `/nc_app_citizens_data`, the container goes *healthy*, `/heartbeat` and
`/api/v1/health` answer, the app runs as uid 10001 and owns the volume; a
volume left owned by root is repaired at start; and in HaRP mode
(`HP_SHARED_KEY` set) the app listens on `/tmp/exapp.sock`, `frpc` runs as
uid 10001 with a 0600 configuration and keeps retrying while HaRP is
unreachable, without ever taking the app down. The entrypoint runs as root for
exactly those repairs and drops privileges with `setpriv`; the image sets no
`USER` because HaRP's certificate step and AppAPI's CA injection `docker exec`
as the image user.

What the smoke test cannot replace: a real HaRP daemon (frps with TLS and the
certificates it injects). Before relying on a HaRP install, register the image
on a scratch instance with such a daemon, print a QR code, record from a phone,
get a transcript and a report. Do this on a scratch instance, not on one
holding real assembly data: installing the same app id through a different
daemon replaces the existing registration.

## Checklist

- [ ] `make appstore-check` passes
- [ ] `make lint && make test` pass, bundles rebuilt and committed
- [ ] Screenshots in `img/screenshots/` still reflect the UI
- [ ] `CHANGELOG.md` has a section for this version
- [ ] Tag matches `<version>` and `<image-tag>`
- [ ] Image is public on GHCR and has both architectures
      (`docker buildx imagetools inspect ghcr.io/democracy-routes/citizens:<version>`)
