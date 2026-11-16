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


def _table_recording(client, assembly, index):
    import re

    token = re.search(r"#/join/(.+)$", assembly["invites"][index]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token},
        headers={"X-Origin-IP": f"203.0.113.{20 + index}"},
    ).json()
    headers = {"Authorization": f"Bearer {joined['session_token']}"}
    recording_id = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": joined["rounds"][0]["id"], "mime_type": "audio/webm;codecs=opus"},
        headers=headers,
    ).json()["recording_id"]
    return headers, recording_id


def _put_chunk(client, headers, recording_id, sequence, body):
    return client.post(
        f"/api/v1/public/recorder/recordings/{recording_id}/chunks/{sequence}",
        content=body,
        headers={**headers, "Content-Type": "application/octet-stream",
                 "X-Chunk-SHA256": hashlib.sha256(body).hexdigest()},
    )


def test_a_recording_past_its_allowance_is_refused_but_another_table_is_not(client, monkeypatch):
    from citizens.services import recording as rec_svc

    assembly = _assembly(client, tables=2)
    first_headers, first = _table_recording(client, assembly, 0)
    second_headers, second = _table_recording(client, assembly, 1)
    chunk = b"a" * 1000
    monkeypatch.setattr(rec_svc, "MAX_RECORDING_BYTES", 3 * len(chunk))
    for sequence in range(3):
        assert _put_chunk(client, first_headers, first, sequence, chunk).status_code == 200
    refused = _put_chunk(client, first_headers, first, 3, chunk)
    assert refused.status_code == 413
    assert "allowance" in refused.json()["detail"]
    assert _put_chunk(client, second_headers, second, 0, chunk).status_code == 200


def test_an_assembly_past_its_allowance_is_refused_across_tables(client, monkeypatch):
    from citizens.services import recording as rec_svc

    assembly = _assembly(client, tables=2)
    first_headers, first = _table_recording(client, assembly, 0)
    second_headers, second = _table_recording(client, assembly, 1)
    chunk = b"b" * 1000
    monkeypatch.setattr(rec_svc, "MAX_ASSEMBLY_AUDIO_BYTES", 3 * len(chunk))
    assert _put_chunk(client, first_headers, first, 0, chunk).status_code == 200
    assert _put_chunk(client, first_headers, first, 1, chunk).status_code == 200
    assert _put_chunk(client, second_headers, second, 0, chunk).status_code == 200
    refused = _put_chunk(client, second_headers, second, 1, chunk)
    assert refused.status_code == 413 and "allowance" in refused.json()["detail"]


def test_a_part_past_the_recording_allowance_is_refused(client, monkeypatch):
    from citizens.services import recording as rec_svc

    assembly = _assembly(client)
    headers, recording_id = _table_recording(client, assembly, 0)
    chunk = b"c" * 1000
    monkeypatch.setattr(rec_svc, "MAX_RECORDING_BYTES", 2 * len(chunk))
    assert _put_chunk(client, headers, recording_id, 0, chunk).status_code == 200
    assert _put_chunk(client, headers, recording_id, 1, chunk).status_code == 200
    part = b"d" * 1000
    refused = client.post(
        f"/api/v1/public/recorder/recordings/{recording_id}/chunks/2/parts/0",
        content=part,
        headers={**headers, "Content-Type": "application/octet-stream",
                 "X-Chunk-SHA256": hashlib.sha256(part).hexdigest(),
                 "X-Part-SHA256": hashlib.sha256(part).hexdigest(),
                 "X-Total-Bytes": str(len(part))},
    )
    assert refused.status_code == 413, refused.text
    assert "allowance" in refused.json()["detail"]
