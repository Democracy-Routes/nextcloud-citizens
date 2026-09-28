# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The QR codes must point at Nextcloud's PUBLIC address.

Built on NEXTCLOUD_URL they worked on the first server only because the
operator had typed the public address into the deploy daemon. AppAPI's own
docker-install passes the address the container uses to reach Nextcloud —
frequently an internal name no phone can open — so the app now asks
Nextcloud for overwrite.cli.url, and an operator can override it.
"""

import pytest

from citizens.config import get_settings
from citizens.services import public_url
from citizens.services.invites import recorder_join_url

PAGE = "/index.php/apps/app_api/proxy/citizens/recorder.html"


@pytest.fixture(autouse=True)
def _fresh(settings_env):
    public_url.reset()
    yield
    public_url.reset()
    get_settings.cache_clear()


def _settings(monkeypatch, **env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()


def test_the_override_wins_over_everything(monkeypatch):
    _settings(monkeypatch, CITIZENS_PUBLIC_URL="https://cloud.example.org/nextcloud/")
    monkeypatch.setattr(public_url, "_lookup", lambda: "https://wrong.example/x.html")

    public_url.refresh()

    assert public_url.recorder_page_url() == "https://cloud.example.org/nextcloud" + PAGE
    assert recorder_join_url("tok") == "https://cloud.example.org/nextcloud" + PAGE + "#/join/tok"


def test_nextcloud_s_public_address_is_used_once_known(monkeypatch):
    _settings(monkeypatch, NEXTCLOUD_URL="http://nextcloud:80", APP_SECRET="s")
    monkeypatch.setattr(public_url, "_lookup", lambda: "https://cloud.example.org" + PAGE)

    # before the first refresh: the only address we have
    assert public_url.recorder_page_url() == "http://nextcloud:80" + PAGE

    assert public_url.refresh() == "https://cloud.example.org" + PAGE
    assert recorder_join_url("tok") == "https://cloud.example.org" + PAGE + "#/join/tok"


def test_a_relative_answer_means_overwrite_cli_url_is_unset(monkeypatch):
    _settings(monkeypatch, NEXTCLOUD_URL="https://cloud.example.org/", APP_SECRET="s")
    monkeypatch.setattr(public_url, "_lookup", lambda: PAGE)

    public_url.refresh()

    assert public_url.recorder_page_url() == "https://cloud.example.org" + PAGE


def test_a_failed_lookup_keeps_the_previous_answer(monkeypatch):
    _settings(monkeypatch, NEXTCLOUD_URL="http://nextcloud", APP_SECRET="s")
    monkeypatch.setattr(public_url, "_lookup", lambda: "https://cloud.example.org" + PAGE)
    public_url.refresh()

    def boom():
        raise ConnectionError("nextcloud is restarting")

    monkeypatch.setattr(public_url, "_lookup", boom)
    public_url.refresh()

    assert public_url.recorder_page_url() == "https://cloud.example.org" + PAGE


def test_nothing_is_asked_without_credentials(monkeypatch):
    """A container missing APP_SECRET cannot sign an OCS request; asking
    would only raise. The address falls back and the app keeps serving."""
    _settings(monkeypatch, NEXTCLOUD_URL="https://cloud.example.org", APP_SECRET="")
    calls = []
    monkeypatch.setattr(public_url, "_lookup", lambda: calls.append(1) or "x")

    public_url.refresh()

    assert calls == []
    assert public_url.recorder_page_url() == "https://cloud.example.org" + PAGE
