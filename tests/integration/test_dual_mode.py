# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The same scenario in both deployment modes.

Nextcloud mode is the regression gate for everything; this file is the one
place where the standalone mode must behave identically on the paths that
matter for an assembly: ownership, the invite links the QR codes carry, a
phone joining and uploading, and an administrator saving Settings. A step
that passes in one mode and not the other is a mode bug, not a feature.
"""

import hashlib
import re

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from citizens.api.admin import get_config_store, require_admin
from citizens.config import get_settings
from citizens.db.session import session_scope
from citizens.main import create_app
from citizens.security.identity import get_current_user_id
from citizens.security.sessions import CLIENT_HEADER, CLIENT_HEADER_VALUE
from citizens.services import accounts, provider_config, public_url

MODES = ("nextcloud", "standalone")


class MemoryStore:
    """Nextcloud mode's Settings store in tests (no Nextcloud to talk to)."""

    def __init__(self):
        self.values: dict[str, str] = {}

    def get_value(self, key):
        return self.values.get(key)

    def set_value(self, key, value, sensitive=False):
        self.values[key] = value

    def delete_value(self, key):
        self.values.pop(key, None)


class Modes:
    """One handle per test: `as_user(name, admin=False)` returns a client
    acting as that person in the mode under test."""

    def __init__(self, mode: str, app):
        self.mode = mode
        self.app = app
        self._store = MemoryStore()

    def as_user(self, name: str, admin: bool = False) -> TestClient:
        if self.mode == "nextcloud":
            client = TestClient(self.app)
            client.headers.update({"X-Test-User": name})
            if admin:
                self.app.dependency_overrides[require_admin] = lambda: name
                self.app.dependency_overrides[get_config_store] = lambda: self._store
            return client
        with session_scope() as session:
            if session.query(accounts.AppUser).filter_by(username=name).first() is None:
                accounts.create_user(
                    session, username=name, role="admin" if admin else "organizer",
                    password="a-good-password",
                )
        client = TestClient(self.app, base_url="https://testserver")
        client.headers.update({CLIENT_HEADER: CLIENT_HEADER_VALUE})
        login = client.post("/api/v1/auth/login", json={"username": name, "password": "a-good-password"})
        assert login.status_code == 200, login.text
        return client


@pytest.fixture(params=MODES)
def modes(request, tmp_path, monkeypatch):
    mode = request.param
    monkeypatch.setenv("APP_ID", "citizens")
    monkeypatch.setenv("APP_VERSION", "0.0.0-test")
    monkeypatch.setenv("APP_SECRET", "test-secret")
    monkeypatch.setenv("APP_PERSISTENT_STORAGE", str(tmp_path / "storage"))
    monkeypatch.setenv("CITIZENS_DEV", "0")
    monkeypatch.setenv("CITIZENS_SMTP_URL", "")
    if mode == "standalone":
        monkeypatch.setenv("CITIZENS_MODE", "standalone")
        monkeypatch.setenv("NEXTCLOUD_URL", "")
        monkeypatch.setenv("CITIZENS_PUBLIC_URL", "https://citizens.test")
    else:
        monkeypatch.delenv("CITIZENS_MODE", raising=False)
        monkeypatch.setenv("NEXTCLOUD_URL", "http://nextcloud.test")
        monkeypatch.setenv("CITIZENS_PUBLIC_URL", "")
    get_settings.cache_clear()
    provider_config.reset_default_store()
    provider_config.invalidate_snapshot()
    public_url.reset()
    app = create_app(with_auth=mode == "standalone")
    if mode == "nextcloud":
        def fake_user(request: Request) -> str:
            return request.headers.get("x-test-user", "tester")

        app.dependency_overrides[get_current_user_id] = fake_user
    with TestClient(app):
        yield Modes(mode, app)
    get_settings.cache_clear()
    provider_config.reset_default_store()
    provider_config.invalidate_snapshot()
    public_url.reset()


def _assembly(client, name="TEST Dual mode"):
    created = client.post(
        "/api/v1/assemblies",
        json={
            "name": name,
            "default_table_count": 1,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    )
    assert created.status_code == 201, created.text
    assembly = created.json()
    assert client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/start").status_code == 200
    return assembly


def test_ownership_is_per_person_in_both_modes(modes):
    anna = modes.as_user("anna")
    bruno = modes.as_user("bruno")
    assembly = _assembly(anna)
    assert [a["id"] for a in anna.get("/api/v1/assemblies").json()] == [assembly["id"]]
    assert bruno.get("/api/v1/assemblies").json() == []
    assert bruno.get(f"/api/v1/assemblies/{assembly['id']}").status_code == 404
    assert anna.get(f"/api/v1/assemblies/{assembly['id']}").status_code == 200


def test_qr_links_phone_join_and_upload(modes):
    anna = modes.as_user("anna")
    assembly = _assembly(anna)
    invites = anna.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    url = invites[0]["url"]
    expected_page = {
        "nextcloud": "http://nextcloud.test/index.php/apps/app_api/proxy/citizens/recorder.html",
        "standalone": "https://citizens.test/recorder.html",
    }[modes.mode]
    assert url.startswith(expected_page + "#/join/"), url
    # the vault gives the same token back when the links are re-read
    links = anna.get(f"/api/v1/assemblies/{assembly['id']}/invites/links").json()
    assert links[0]["url"] == url

    token = re.search(r"#/join/(.+)$", url).group(1)
    # the phone: no cookie, no client header — a bearer token only
    phone = TestClient(modes.app, base_url="https://testserver")
    joined = phone.post("/api/v1/public/join", json={"token": token}, headers={"X-Origin-IP": "203.0.113.7"})
    assert joined.status_code == 200, joined.text
    bearer = {"Authorization": f"Bearer {joined.json()['session_token']}"}
    started = phone.post(
        "/api/v1/public/recorder/start",
        json={"round_id": assembly["rounds"][0]["id"], "mime_type": "audio/webm;codecs=opus"},
        headers=bearer,
    )
    assert started.status_code == 201, started.text
    recording_id = started.json()["recording_id"]
    blob = b"audio-bytes"
    uploaded = phone.post(
        f"/api/v1/public/recorder/recordings/{recording_id}/chunks/0",
        content=blob,
        headers={**bearer, "Content-Type": "application/octet-stream",
                 "X-Chunk-SHA256": hashlib.sha256(blob).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text
    status = phone.get("/api/v1/public/recorder/status", headers=bearer)
    assert status.status_code == 200
    # the organizer sees the table live
    assert anna.get(f"/api/v1/assemblies/{assembly['id']}").status_code == 200


def test_admin_saves_settings_and_reads_them_back(modes):
    organizer = modes.as_user("anna")
    assert organizer.get("/api/v1/admin/providers").status_code in (401, 403)
    admin = modes.as_user("root", admin=True)
    saved = admin.put(
        "/api/v1/admin/providers",
        json={"organization_name": "Comune di Prova", "audio_retention_days": 12},
    )
    assert saved.status_code == 200, saved.text
    summary = admin.get("/api/v1/admin/providers").json()
    assert summary["organization_name"] == "Comune di Prova"
    assert summary["audio_retention_days"] == 12
