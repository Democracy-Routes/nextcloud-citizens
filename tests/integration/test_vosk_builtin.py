# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vosk built into the app container (0.8): the setting, the model installs
from Settings, and the loopback engine answering the protocol the clients
speak."""

import io
import json
import time
import zipfile

import pytest

from citizens.api.admin import get_config_store, require_admin
from citizens.services import provider_config, vosk_builtin, vosk_models
from tests.integration.test_admin_providers import MemoryStore


@pytest.fixture
def admin(client):
    store = MemoryStore()
    client.app.dependency_overrides[get_config_store] = lambda: store
    client.app.dependency_overrides[require_admin] = lambda: "tester"
    yield client, store
    vosk_models.PROGRESS.clear()
    vosk_builtin.BUILTIN.stop()


def _zip_model(name: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(f"{name}/am/final.mdl", b"model bytes")
        zf.writestr(f"{name}/conf/model.conf", "--sample-frequency=16000\n")
    return buffer.getvalue()


def test_the_mode_setting_travels_through_settings(admin):
    client, store = admin
    before = client.get("/api/v1/admin/providers").json()
    assert before["stt"]["vosk_mode"] == "server"
    saved = client.put("/api/v1/admin/providers", json={"vosk_mode": "builtin"})
    assert saved.status_code == 200 and saved.json()["stt"]["vosk_mode"] == "builtin"
    assert provider_config.vosk_endpoint(store) == provider_config.BUILTIN_VOSK_URL
    assert provider_config.vosk_model_path("vosk-model-small-it-0.22", builtin=True).endswith(
        "/models/vosk-model-small-it-0.22"
    )
    assert client.put("/api/v1/admin/providers", json={"vosk_mode": "cloud"}).status_code == 422


def test_a_model_is_installed_from_settings_and_removed_again(admin, monkeypatch, settings_env):
    client, _store = admin
    name = "vosk-model-small-it-0.22"

    def fake_download(url, target, model_name):
        assert url.endswith(f"/{name}.zip")
        vosk_models._set_progress(model_name, phase="downloading", received=5, total=10)
        target.write_bytes(_zip_model(name))

    monkeypatch.setattr(vosk_models, "_download", fake_download)
    assert client.post("/api/v1/admin/vosk/models/not-a-model/install").status_code == 422
    assert client.post("/api/v1/admin/vosk/models/vosk-model-xx-9.9/install").status_code == 404
    queued = client.post(f"/api/v1/admin/vosk/models/{name}/install")
    assert queued.status_code == 202, queued.text
    assert client.post(f"/api/v1/admin/vosk/models/{name}/install").status_code == 409

    deadline = time.time() + 30
    while time.time() < deadline:
        overview = client.get("/api/v1/admin/vosk/models").json()
        if any(m["name"] == name for m in overview["installed"]):
            break
        time.sleep(0.3)
    installed = next(m for m in overview["installed"] if m["name"] == name)
    assert installed["usable"] is True and installed["language"] == "it"
    assert (settings_env.app_persistent_storage / "models" / name / "am" / "final.mdl").is_file()
    assert not list((settings_env.app_persistent_storage / "temp").glob("vosk-*"))
    assert name not in [e["name"] for e in overview["available"]]

    assert client.post(f"/api/v1/admin/vosk/models/{name}/cancel").status_code == 404
    removed = client.delete(f"/api/v1/admin/vosk/models/{name}")
    assert removed.status_code == 200 and removed.json()["freed_bytes"] > 0
    assert client.delete(f"/api/v1/admin/vosk/models/{name}").status_code == 404
    assert name in [e["name"] for e in client.get("/api/v1/admin/vosk/models").json()["available"]]


def test_a_broken_archive_fails_cleanly(admin, monkeypatch, settings_env):
    client, _store = admin
    name = "vosk-model-small-en-us-0.15"
    monkeypatch.setattr(vosk_models, "_download", lambda url, target, n: target.write_bytes(b"nope"))
    assert client.post(f"/api/v1/admin/vosk/models/{name}/install").status_code == 202
    deadline = time.time() + 30
    progress = None
    while time.time() < deadline:
        overview = client.get("/api/v1/admin/vosk/models").json()
        progress = next(e["progress"] for e in overview["available"] if e["name"] == name)
        if progress and progress["phase"] in ("done", "failed"):
            break
        time.sleep(0.3)
    assert progress["phase"] == "failed" and "BadZipFile" in progress["error"]
    assert not (settings_env.app_persistent_storage / "models" / name).exists()


def test_the_loopback_engine_speaks_the_protocol(tmp_path):
    pytest.importorskip("vosk")
    from websockets.sync.client import connect

    server = vosk_builtin.BuiltinVoskServer()
    assert server.start(str(tmp_path), port=27010) is True
    assert server.status()["running"] is True
    with connect("ws://127.0.0.1:27010") as ws:
        ws.send(json.dumps({"config": {"sample_rate": 16000, "model": str(tmp_path / "missing")}}))
        answer = json.loads(ws.recv())
        assert "error" in answer and "no such model" in answer["error"]
    with connect("ws://127.0.0.1:27010") as ws:
        ws.send(b"\x00" * 6400)  # audio before any model: refused, not crashed
        answer = json.loads(ws.recv())
        assert "error" in answer
    server.stop()
    assert server.status()["running"] is False


def test_a_model_larger_than_the_free_memory_is_refused(tmp_path, monkeypatch):
    pytest.importorskip("vosk")
    from websockets.sync.client import connect

    model = tmp_path / "vosk-model-huge"
    (model / "am").mkdir(parents=True)
    (model / "am" / "final.mdl").write_bytes(b"x" * 10_000)
    monkeypatch.setattr(vosk_builtin, "memory_available", lambda: 1000)
    server = vosk_builtin.BuiltinVoskServer()
    assert server.start(str(tmp_path), port=27011)
    with connect("ws://127.0.0.1:27011") as ws:
        ws.send(json.dumps({"config": {"model": str(model)}}))
        answer = json.loads(ws.recv())
        assert "error" in answer and "MB are free" in answer["error"]
    server.stop()
