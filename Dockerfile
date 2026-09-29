# Nextcloud Citizens — ExApp runtime image.
#
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Build with --build-arg WITH_TEST_TOOLS=1 for the image `make test` uses
# (adds espeak-ng for synthetic-speech transcription tests). The published
# image never carries test tooling.
FROM python:3.12-slim

ARG WITH_TEST_TOOLS=0
# Set by BuildKit/buildx (release.yml builds linux/amd64 and linux/arm64);
# `uname -m` is the fallback for a plain `docker build`.
ARG TARGETARCH
# frp pin and tarball checksums: the same ones as HaRP's README and
# nextcloud/app-skeleton-python, so the client matches the frps HaRP runs.
ARG FRP_VERSION=0.61.1
ARG FRP_AMD64_SHA256=bff260b68ca7b1461182a46c4f34e9709ba32764eed30a15dd94ac97f50a2c40
ARG FRP_ARM64_SHA256=af6366f2b43920ebfe6235dba6060770399ed1fb18601e5818552bd46a7621f8

# ffmpeg: audio assembly/validation. fonts-dejavu-core: Unicode font embedded
# in PDF reports. curl: HEALTHCHECK and the frpc download below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core curl \
    && if [ "$WITH_TEST_TOOLS" = "1" ]; then apt-get install -y --no-install-recommends espeak-ng; fi \
    && rm -rf /var/lib/apt/lists/*

# frpc: under a HaRP deploy daemon the app listens on a unix socket and this
# client tunnels it to HaRP (see start.sh). Verified against the per-arch
# tarball checksum, as Nextcloud's skeleton does.
RUN set -eu; \
    case "${TARGETARCH:-$(uname -m)}" in \
        arm64|aarch64) FRP_ARCH=arm64; FRP_SHA256="$FRP_ARM64_SHA256" ;; \
        amd64|x86_64)  FRP_ARCH=amd64; FRP_SHA256="$FRP_AMD64_SHA256" ;; \
        *) echo "unsupported architecture: ${TARGETARCH:-$(uname -m)}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_${FRP_ARCH}.tar.gz" -o /tmp/frp.tar.gz; \
    echo "${FRP_SHA256}  /tmp/frp.tar.gz" | sha256sum -c -; \
    tar -C /tmp -xzf /tmp/frp.tar.gz "frp_${FRP_VERSION}_linux_${FRP_ARCH}/frpc"; \
    install -m 0755 "/tmp/frp_${FRP_VERSION}_linux_${FRP_ARCH}/frpc" /usr/local/bin/frpc; \
    rm -rf /tmp/frp.tar.gz "/tmp/frp_${FRP_VERSION}_linux_${FRP_ARCH}"; \
    frpc --version

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY citizens ./citizens
COPY appinfo ./appinfo
# UI bundles: the organizer app (js + css) and the public table recorder.
# Missing any of these leaves the deployed app unstyled or the recorder dead.
COPY js ./js
COPY css ./css
COPY img ./img
COPY recorder_static ./recorder_static
COPY start.sh healthcheck.sh ./
RUN pip install --no-cache-dir . && chmod +x start.sh healthcheck.sh

# APP_HOST: nc_py_api's run_app defaults to 127.0.0.1, which is unreachable
# from Nextcloud; a container must listen on all interfaces. AppAPI normally
# injects these three, but the image must be correct on its own.
ENV APP_PERSISTENT_STORAGE=/data \
    APP_HOST=0.0.0.0 \
    APP_PORT=23000 \
    NPA_TIMEOUT=10

# NPA_TIMEOUT: nc_py_api's per-call timeout towards Nextcloud, 30 s by
# default. Every OCS call the app makes goes through the same Apache workers
# that serve the phones, so a Nextcloud that is slow because the app is busy
# must not park a thread (and, before 0.6.2, a database connection) for half
# a minute. Nothing the app asks Nextcloud takes more than a second.

# The service user. Explicit gid: `useradd --system` alone picks gid 999.
# /data is the hand-run deployment's mount; /nc_app_citizens_data is where
# AppAPI's docker-install mounts its named volume — an EMPTY named volume
# inherits the ownership of the image directory on first mount, so this is
# what makes a fresh install writable (start.sh repairs the other cases).
# /certs/frp is where HaRP drops the frpc client certificates at install.
# No USER: start.sh runs as root, fixes ownership, then drops to 10001 with
# setpriv. AppAPI and HaRP also `docker exec` mkdir and update-ca-certificates
# as the image user, which only works as root.
RUN groupadd --system --gid 10001 citizens \
    && useradd --system --uid 10001 --gid 10001 --home-dir /app citizens \
    && mkdir -p /data /nc_app_citizens_data /certs/frp \
    && chown -R citizens:citizens /app /data /nc_app_citizens_data /certs/frp

EXPOSE 23000

# Answers over TCP or the HaRP unix socket, whichever mode run_app chose.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ./healthcheck.sh

ENTRYPOINT ["./start.sh"]
