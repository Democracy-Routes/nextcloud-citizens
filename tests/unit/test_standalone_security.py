# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Standalone mode's building blocks, without a server: password hashing,
session cookies, the client-address rule, the mail transport parsing."""

import pytest

from citizens.config import get_settings
from citizens.security import passwords, sessions


@pytest.fixture
def standalone_env(monkeypatch):
    monkeypatch.setenv("CITIZENS_MODE", "standalone")
    monkeypatch.setenv("APP_SECRET", "unit-secret")
    monkeypatch.setenv("CITIZENS_PUBLIC_URL", "https://citizens.example.org")
    monkeypatch.setenv("CITIZENS_TRUSTED_PROXIES", "10.0.0.2, 10.0.0.3")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


def test_password_hash_verifies_and_rejects():
    stored = passwords.hash_password("correct horse battery")
    assert stored.startswith("scrypt$14$8$1$")
    assert passwords.verify_password("correct horse battery", stored)
    assert not passwords.verify_password("Correct horse battery", stored)
    assert not passwords.verify_password("", stored)
    assert not passwords.verify_password("anything", None)
    assert not passwords.verify_password("anything", "garbage")


def test_password_rules_are_about_length_only():
    assert passwords.password_problem("short") is not None
    assert passwords.password_problem("a" * 10) is None
    assert passwords.password_problem("a" * 201) is not None


def test_session_cookie_round_trip_and_forgery(standalone_env):
    value = sessions.issue("user-1", now=1_000_000)
    assert sessions.read(value, now=1_000_100) == "user-1"
    # expired after the configured days
    assert sessions.read(value, now=1_000_000 + 15 * 86400) is None
    # a flipped byte in the signature
    payload, signature = value.split(".")
    tampered = payload + "." + ("A" if signature[0] != "A" else "B") + signature[1:]
    assert sessions.read(tampered, now=1_000_100) is None
    # a payload naming another user with the old signature
    other = sessions.issue("user-2", now=1_000_000).split(".")[0] + "." + signature
    assert sessions.read(other, now=1_000_100) is None
    assert sessions.read(None) is None
    assert sessions.read("no-dot") is None


def test_session_signature_changes_with_the_secret(standalone_env, monkeypatch):
    value = sessions.issue("user-1")
    monkeypatch.setenv("APP_SECRET", "another")
    get_settings.cache_clear()
    assert sessions.read(value) is None


def test_client_ip_trusts_forwarded_for_only_from_the_proxy(standalone_env):
    from starlette.requests import Request

    from citizens.security.rate_limit import client_ip

    def request(peer: str, headers: dict[str, str]) -> Request:
        scope = {
            "type": "http", "method": "GET", "path": "/", "headers": [
                (k.lower().encode(), v.encode()) for k, v in headers.items()
            ], "client": (peer, 1234), "query_string": b"",
        }
        return Request(scope)

    # from the proxy: the last hop it appended
    assert client_ip(request("10.0.0.2", {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"})) == "5.6.7.8"
    # from anyone else: the peer, whatever the headers claim
    assert client_ip(request("9.9.9.9", {"X-Forwarded-For": "1.2.3.4"})) == "9.9.9.9"
    assert client_ip(request("9.9.9.9", {"X-Origin-IP": "1.2.3.4"})) == "9.9.9.9"


def test_mail_transport_parsing(standalone_env, monkeypatch):
    from citizens.services import mail

    assert mail.transport().kind == "log"
    assert not mail.configured()
    monkeypatch.setenv("CITIZENS_SMTP_URL", "smtp://user%40x:p%3Dw@mail.example.org:587")
    get_settings.cache_clear()
    transport = mail.transport()
    assert (transport.kind, transport.host) == ("smtp", "mail.example.org")
    assert (transport.port, transport.tls) == (587, "starttls")
    assert (transport.username, transport.password) == ("user@x", "p=w")
    monkeypatch.setenv("CITIZENS_SMTP_URL", "smtps://mail.example.org")
    get_settings.cache_clear()
    assert (mail.transport().port, mail.transport().tls) == (465, "tls")
    monkeypatch.setenv("CITIZENS_SMTP_URL", "smtp://relay:25")
    get_settings.cache_clear()
    assert mail.transport().tls == "none"
    redacted = mail.redact("open https://x/?set-password=abc123&x=1 now")
    assert redacted == "open https://x/?set-password=[redacted]&x=1 now"


def test_mode_is_never_inferred(monkeypatch):
    monkeypatch.delenv("CITIZENS_MODE", raising=False)
    monkeypatch.setenv("NEXTCLOUD_URL", "")
    get_settings.cache_clear()
    assert not get_settings().is_standalone()
    monkeypatch.setenv("CITIZENS_MODE", "standalon")
    get_settings.cache_clear()
    assert not get_settings().is_standalone()
    assert get_settings().mode_problem()
    get_settings.cache_clear()
