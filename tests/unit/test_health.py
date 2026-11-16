# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
from fastapi.testclient import TestClient

from citizens.main import create_app


def test_health_endpoint(settings_env):
    app = create_app(with_auth=False)
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["app"] == "citizens"
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["storage"] == "ok"
    assert body["disk_free_gb"] is not None


def test_standalone_health_is_minimal_without_a_session(tmp_path, monkeypatch):
    from citizens.config import get_settings

    monkeypatch.setenv("APP_ID", "citizens")
    monkeypatch.setenv("APP_VERSION", "0.0.0-test")
    monkeypatch.setenv("APP_SECRET", "test-secret")
    monkeypatch.setenv("NEXTCLOUD_URL", "")
    monkeypatch.setenv("CITIZENS_MODE", "standalone")
    monkeypatch.setenv("CITIZENS_PUBLIC_URL", "https://citizens.test")
    monkeypatch.setenv("CITIZENS_SMTP_URL", "")
    monkeypatch.setenv("CITIZENS_BOOTSTRAP_ADMIN_USER", "boot")
    monkeypatch.setenv("CITIZENS_BOOTSTRAP_ADMIN_PASSWORD", "bootstrap-password")
    monkeypatch.setenv("APP_PERSISTENT_STORAGE", str(tmp_path / "storage"))
    monkeypatch.setenv("CITIZENS_DEV", "0")
    get_settings.cache_clear()
    try:
        with TestClient(create_app(with_auth=True), base_url="https://testserver") as client:
            body = client.get("/api/v1/health").json()
    finally:
        get_settings.cache_clear()
    assert set(body) == {"app", "status"}
