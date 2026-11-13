# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Polis poll on the devices: published like the report, the phones get
the voting link and a QR, the organizer's QR tab and the printable sheet
carry it too."""

import re

from citizens.db.models import Assembly
from citizens.db.session import session_scope


def _make_assembly(client, name="TEST Poll"):
    return client.post(
        "/api/v1/assemblies",
        json={"name": name, "default_table_count": 1,
              "rounds": [{"title": "R1", "question": "Q", "duration_minutes": 10}]},
    ).json()


def _join(client, assembly, ip):
    token = re.search(r"#/join/(.+)$", assembly["invites"][0]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Forwarded-For": ip}
    ).json()
    return {"Authorization": f"Bearer {joined['session_token']}"}


def _sent_to_polis(assembly_id, url="https://polis.example.org/3hjm3feewj"):
    with session_scope() as session:
        assembly = session.get(Assembly, assembly_id)
        assembly.polis_conversation_id = "3hjm3feewj"
        assembly.polis_url = url


def test_the_poll_reaches_the_phones_only_while_published(client):
    assembly = _make_assembly(client)
    url = f"/api/v1/assemblies/{assembly['id']}/seeds"
    headers = _join(client, assembly, "10.9.9.2")

    # nothing sent yet: nothing to publish, nothing on the phone
    assert client.post(f"{url}/poll/publish").status_code == 409
    assert client.get(f"{url}/poll-qr").json()["available"] is False
    assert client.get("/api/v1/public/recorder/status", headers=headers).json()["poll_url"] is None
    assert client.get("/api/v1/public/recorder/poll-qr", headers=headers).json() == {"available": False}

    _sent_to_polis(assembly["id"])
    # sent but not published: the organizer sees the QR, the phones nothing
    organizer = client.get(f"{url}/poll-qr").json()
    assert organizer["available"] is True and organizer["published"] is False
    assert organizer["qr_svg"].startswith("<svg")
    assert client.get("/api/v1/public/recorder/status", headers=headers).json()["poll_url"] is None
    assert client.get(url).json()["polis"]["published_at"] is None

    published = client.post(f"{url}/poll/publish")
    assert published.status_code == 200 and published.json()["published_at"]
    assert client.get(url).json()["polis"]["published_at"]
    status = client.get("/api/v1/public/recorder/status", headers=headers).json()
    assert status["poll_url"] == "https://polis.example.org/3hjm3feewj"
    qr = client.get("/api/v1/public/recorder/poll-qr", headers=headers).json()
    assert qr["available"] is True and qr["url"] == status["poll_url"] and qr["qr_svg"].startswith("<svg")
    assert client.get(f"{url}/poll-qr").json()["published"] is True

    # the printable table sheet gains the vote cards and stays a PDF
    sheet = client.get(f"/api/v1/assemblies/{assembly['id']}/invites/sheet.pdf")
    assert sheet.status_code == 200 and sheet.content.startswith(b"%PDF")

    assert client.delete(f"{url}/poll/publish").status_code == 204
    assert client.get("/api/v1/public/recorder/status", headers=headers).json()["poll_url"] is None
    assert client.get("/api/v1/public/recorder/poll-qr", headers=headers).json() == {"available": False}


def test_the_poll_is_private_to_the_assembly_owner(client):
    assembly = _make_assembly(client, "TEST Poll Owner")
    _sent_to_polis(assembly["id"])
    other = {"X-Test-User": "someone-else"}
    url = f"/api/v1/assemblies/{assembly['id']}/seeds"
    assert client.post(f"{url}/poll/publish", headers=other).status_code == 404
    assert client.get(f"{url}/poll-qr", headers=other).status_code == 404
    assert client.delete(f"{url}/poll/publish", headers=other).status_code == 404
