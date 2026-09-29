# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The request path never asks Nextcloud for its settings.

On 2026-09-29, five phones froze the server for three minutes: every status
poll that found a 30-second cache stale made six OCS calls to Nextcloud with
a database connection checked out, the calls went through the same Apache
workers the phones were occupying, and the pool ran out. Now one reader
fills a snapshot in the background and every request reads memory.
"""

import pytest

from citizens.services import provider_config


class MemoryStore:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.reads = 0
        self.fail = False

    def get_value(self, key):
        self.reads += 1
        if self.fail:
            raise ConnectionError("nextcloud is not answering")
        return self.values.get(key)

    def set_value(self, key, value, sensitive=False):
        self.values[key] = value

    def delete_value(self, key):
        self.values.pop(key, None)


@pytest.fixture
def store(monkeypatch):
    store = MemoryStore({
        "stt_provider": "mistral",
        "mistral_api_key": "mk",
        "analysis_enabled": "1",
        "analysis_api_key": "ak",
        "organization_name": "Democracy Innovators",
        "audio_retention_days": "7",
    })
    monkeypatch.setattr(provider_config, "default_store", lambda: store)
    monkeypatch.setattr(provider_config, "_snapshot", None)
    monkeypatch.setattr(provider_config, "_refresh_failed", False)
    provider_config.refresh_config_snapshot()
    return store


def test_readers_never_touch_the_store(store):
    store.reads = 0

    for _ in range(50):
        assert provider_config.data_handling_summary()["stt_provider"] == "mistral"
        assert provider_config.analysis_enabled_cached() is True
        assert provider_config.analysis_ready_cached() is True
        assert provider_config.live_stt_snapshot()["provider"] == "mistral"
        assert provider_config.organization_name_cached() == "Democracy Innovators"

    assert store.reads == 0


def test_a_failed_refresh_keeps_the_previous_values(store):
    store.fail = True

    snapshot = provider_config.refresh_config_snapshot()

    assert snapshot.ok is False
    assert snapshot.data_handling["stt_provider"] == "mistral"
    assert snapshot.organization_name == "Democracy Innovators"
    assert provider_config.data_handling_summary()["stt_provider"] == "mistral"


def test_nothing_at_all_serves_defaults_rather_than_blocking(monkeypatch):
    broken = MemoryStore()
    broken.fail = True
    monkeypatch.setattr(provider_config, "default_store", lambda: broken)
    monkeypatch.setattr(provider_config, "_snapshot", None)

    assert provider_config.data_handling_summary() == {}
    assert provider_config.analysis_enabled_cached() is True  # the stricter gate
    assert provider_config.analysis_ready_cached() is False
    assert provider_config.live_stt_snapshot()["enabled"] is False
    # and a reader does not retry Nextcloud on every call
    reads = broken.reads
    provider_config.data_handling_summary()
    assert broken.reads == reads


def test_saving_settings_reads_them_again_at_once(store):
    store.set_value("organization_name", "Comune di Bologna")
    assert provider_config.organization_name_cached() == "Democracy Innovators"

    provider_config.invalidate_snapshot()

    assert provider_config.organization_name_cached() == "Comune di Bologna"


def test_a_stale_snapshot_is_refreshed_in_the_background(store, monkeypatch):
    store.set_value("stt_provider", "deepgram")
    monkeypatch.setattr(provider_config, "_LIVE_SNAPSHOT_TTL", 0.0)

    first = provider_config.data_handling_summary()  # stale answer, refresh kicked off
    thread = provider_config._refresh_thread
    assert thread is not None
    thread.join(timeout=5)

    assert first["stt_provider"] == "mistral"
    assert provider_config.data_handling_summary()["stt_provider"] == "deepgram"


def test_a_swapped_store_is_read_afresh(store, monkeypatch):
    other = MemoryStore({"stt_provider": "vosk", "vosk_url": "http://vosk.internal:2700"})
    monkeypatch.setattr(provider_config, "default_store", lambda: other)

    summary = provider_config.data_handling_summary()

    assert summary["stt_provider"] == "vosk"
    assert summary["stt_hosted"] is False
