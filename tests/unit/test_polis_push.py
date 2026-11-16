# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Polis bridge, the pure parts: how Polis's answers are read, which
refusals are permanent, and how a refusal's positions come back out of the
job's failure text."""

import json

import httpx
import pytest

from citizens.services import polis


class FakeResponse:
    def __init__(self, status_code, body=None, text="", headers=None):
        self.status_code = status_code
        self._body = body
        self.text = text if body is None else json.dumps(body)
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def test_personal_data_refusal_is_permanent_and_names_the_positions():
    refusal = polis._refusal(FakeResponse(400, {
        "error": "polis_err_citizens_import_personal_data",
        "details": [{"position": 7, "reason": "email"}, {"position": 3, "reason": "table"}, "nonsense"],
    }))
    assert refusal.permanent is True and refusal.positions == [3, 7]
    assert "positions 3, 7" in str(refusal)
    assert polis.refused_positions(str(refusal)) == [3, 7]
    assert polis.refused_positions("Polis returned HTTP 500: boom") == []
    assert polis.refused_positions(None) == []


def test_other_answers_map_to_permanent_or_retry():
    invalid = polis._refusal(FakeResponse(400, {
        "error": "polis_err_citizens_import_invalid",
        "details": [{"field": "statements", "reason": "1-200 statements"}],
    }))
    assert invalid.permanent and "statements: 1-200" in str(invalid)
    key = polis._refusal(FakeResponse(403, {"error": "polis_err_auth_no_such_api_token"}))
    assert key.permanent and key.status == 403
    missing = polis._refusal(FakeResponse(404, text="<html>not found</html>"))
    assert missing.permanent and "no Citizens endpoint" in str(missing)
    limited = polis._refusal(FakeResponse(429, {"error": "polis_err_citizens_import_rate_limited"},
                                          headers={"retry-after": "30"}))
    assert limited.permanent is False and limited.retry_after == 30.0
    down = polis._refusal(FakeResponse(502, text="bad gateway"))
    assert down.permanent is False and down.status == 502


def test_ping_reports_the_key_owner_and_never_the_key(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"], seen["auth"] = url, headers["Authorization"]
        return FakeResponse(200, {"ok": True, "owner_email": "ops@example.org"})

    monkeypatch.setattr(polis.httpx, "get", fake_get)
    result = polis.ping("https://polis.example.org/", "k-secret-1234")
    assert result == {"ok": True, "message": "Connected — key of ops@example.org"}
    assert seen["url"] == "https://polis.example.org/api/v3/citizens/ping"
    assert seen["auth"] == "Bearer k-secret-1234"

    monkeypatch.setattr(polis.httpx, "get", lambda *a, **k: FakeResponse(403, {"error": "no"}))
    assert polis.ping("https://polis.example.org", "k")["ok"] is False
    monkeypatch.setattr(polis.httpx, "get", lambda *a, **k: FakeResponse(404, text="nope"))
    assert "Citizens-Polis fork" in polis.ping("https://polis.example.org", "k")["message"]

    def unreachable(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(polis.httpx, "get", unreachable)
    assert "ConnectError" in polis.ping("https://polis.example.org", "k")["message"]


@pytest.mark.parametrize("value", ["", "not-a-list"])
def test_positions_tolerate_odd_details(value):
    assert polis._positions(value) == []


def test_a_link_that_is_not_http_is_dropped_and_the_others_kept(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    body = {
        "conversation_id": "abc", "url": "javascript:alert(1)",
        "moderation_url": "https://polis.example/m", "report_url": "//no-scheme.example/r",
        "statements": {"results": []},
    }
    monkeypatch.setattr(polis.provider_config, "polis_config", lambda store: ("https://polis.example", "k"))
    monkeypatch.setattr(polis.seeds_svc, "list_seeds", lambda session, assembly_id: [object()])
    monkeypatch.setattr(polis.seeds_svc, "exportable", lambda rows: rows)
    monkeypatch.setattr(polis.seeds_svc, "render_json", lambda assembly, chosen, now: "{}")
    monkeypatch.setattr(polis.seeds_svc, "mark_exported", lambda chosen, now: None)
    monkeypatch.setattr(polis.httpx, "post", lambda *a, **k: FakeResponse(200, body))
    assembly = SimpleNamespace(id="a1", name="A", description="")
    polis.push(MagicMock(), object(), assembly)
    assert assembly.polis_url is None
    assert assembly.polis_moderation_url == "https://polis.example/m"
    assert assembly.polis_report_url is None
