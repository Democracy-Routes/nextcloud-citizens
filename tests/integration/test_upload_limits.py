# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A public route must not buffer an unbounded body.

The chunk upload deliberately reads the body BEFORE authenticating, so that
resolving the bearer token does not hold SQLite's write lock for the length of
an upload over venue WiFi. The cost of that ordering is that an unauthenticated
caller reaches the body read — so the size limit has to live there too.

Without it, `POST .../chunks/0` with a 500 MB body is buffered in full and only
then answered 401. A handful in parallel is enough to OOM the container in the
middle of an assembly.
"""

import hashlib

from citizens.api.limits import MAX_REQUEST_BYTES
from citizens.services.recording import MAX_CHUNK_BYTES

OVERSIZED = b"x" * (MAX_CHUNK_BYTES + 1024)


def _assembly(client, tables=1):
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Upload Limits",
            "default_table_count": tables,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()
    client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/start")
    return assembly


def _join(client, assembly):
    import re

    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Origin-IP": "203.0.113.7"}
    ).json()
    return {"Authorization": f"Bearer {joined['session_token']}"}, joined["rounds"][0]["id"]


def test_an_oversized_chunk_is_refused_without_authentication(client):
    """No bearer token at all: the body must be refused on size, not buffered
    to completion and then answered 401."""
    response = client.post(
        "/api/v1/public/recorder/recordings/whatever/chunks/0",
        content=OVERSIZED,
        headers={
            "Content-Type": "application/octet-stream",
            "X-Chunk-SHA256": hashlib.sha256(OVERSIZED).hexdigest(),
        },
    )
    assert response.status_code == 413, (
        f"expected 413, got {response.status_code} — an unauthenticated caller "
        "was able to have a body of this size buffered"
    )


def test_an_oversized_chunk_from_a_real_table_is_refused_and_stores_nothing(client):
    assembly = _assembly(client)
    headers, round_id = _join(client, assembly)
    recording_id = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": round_id, "mime_type": "audio/webm;codecs=opus"},
        headers=headers,
    ).json()["recording_id"]

    response = client.post(
        f"/api/v1/public/recorder/recordings/{recording_id}/chunks/0",
        content=OVERSIZED,
        headers={
            **headers,
            "Content-Type": "application/octet-stream",
            "X-Chunk-SHA256": hashlib.sha256(OVERSIZED).hexdigest(),
        },
    )
    assert response.status_code == 413

    state = client.get(
        f"/api/v1/public/recorder/recordings/{recording_id}", headers=headers
    ).json()
    assert state["received_chunks"] == 0, "an over-sized chunk was recorded anyway"


def test_a_chunk_at_the_limit_is_still_accepted(client):
    """The cap must not be off by one against a legitimate maximum chunk."""
    assembly = _assembly(client)
    headers, round_id = _join(client, assembly)
    recording_id = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": round_id, "mime_type": "audio/webm;codecs=opus"},
        headers=headers,
    ).json()["recording_id"]

    body = b"y" * MAX_CHUNK_BYTES
    response = client.post(
        f"/api/v1/public/recorder/recordings/{recording_id}/chunks/0",
        content=body,
        headers={
            **headers,
            "Content-Type": "application/octet-stream",
            "X-Chunk-SHA256": hashlib.sha256(body).hexdigest(),
        },
    )
    assert response.status_code == 200, response.text


def test_the_log_endpoint_cannot_be_used_to_buffer_a_huge_body(client):
    """LogsIn caps the list at 200 entries, but pydantic only sees the body
    once it is already in memory. The middleware is what bounds it."""
    response = client.post(
        "/api/v1/public/recorder/logs",
        content=b"z" * (MAX_REQUEST_BYTES + 1024),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
