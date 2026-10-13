# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Settings opens from memory (0.7.0-beta.1): the cached summary serves
every AppConfigStore, and a refresh reads every key in one call."""

from citizens.services import provider_config
from citizens.services.provider_config import AppConfigStore, bulk_view, settings_summary


class _Record:
    def __init__(self, key, value):
        self.key, self.value = key, value


class _FakeAppConfig:
    def __init__(self, values):
        self.values = values
        self.single_calls = 0
        self.bulk_calls = 0

    def get_value(self, key):
        self.single_calls += 1
        return self.values.get(key)

    def get_values(self, keys):
        self.bulk_calls += 1
        return [_Record(k, self.values[k]) for k in keys if k in self.values]

    def set_value(self, key, value, sensitive=False):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class _FakeNc:
    def __init__(self, values):
        self.appconfig_ex = _FakeAppConfig(values)


def _fresh(monkeypatch, values):
    nc = _FakeNc(values)
    background = AppConfigStore(nc)
    monkeypatch.setattr(provider_config, "_background_store", background)
    monkeypatch.setattr(provider_config, "default_store", lambda: background)
    monkeypatch.setattr(provider_config, "_snapshot", None)
    monkeypatch.setattr(provider_config, "_refresh_failed", False)
    return nc


def test_a_refresh_reads_every_key_in_one_call(monkeypatch):
    nc = _fresh(monkeypatch, {"stt_provider": "vosk", "organization_name": "Comune", "analysis_api_key": "k"})
    snapshot = provider_config.refresh_config_snapshot(with_summary=True)
    assert nc.appconfig_ex.bulk_calls == 1
    assert nc.appconfig_ex.single_calls == 0, "no per-key reads behind the bulk read"
    assert snapshot.organization_name == "Comune"
    assert snapshot.summary["stt"]["provider"] == "vosk"


def test_settings_is_served_from_memory_to_every_request_store(monkeypatch):
    nc = _fresh(monkeypatch, {"organization_name": "Comune"})
    provider_config.refresh_config_snapshot(with_summary=True)
    calls = (nc.appconfig_ex.bulk_calls, nc.appconfig_ex.single_calls)
    # the admin route builds a new store per request
    for _ in range(3):
        summary = settings_summary(AppConfigStore(_FakeNc({"organization_name": "stale"})))
        assert summary["organization_name"] == "Comune"
    assert (nc.appconfig_ex.bulk_calls, nc.appconfig_ex.single_calls) == calls


def test_a_key_the_bulk_read_did_not_cover_is_still_answered(monkeypatch):
    nc = _fresh(monkeypatch, {"organization_name": "Comune", "unlisted": "x"})
    view = bulk_view(provider_config.default_store())
    assert view.get_value("organization_name") == "Comune"
    assert nc.appconfig_ex.single_calls == 0
    assert view.get_value("unlisted") == "x"
    assert nc.appconfig_ex.single_calls == 1


def test_a_store_without_bulk_reads_is_used_as_it_is():
    class Plain:
        def get_value(self, key):
            return None

        def set_value(self, key, value, sensitive=False):
            pass

        def delete_value(self, key):
            pass

    plain = Plain()
    assert bulk_view(plain) is plain
