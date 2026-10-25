# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The organizer bundle is never stale (0.8): the registered paths answer a
loader stamped with the running version, never cached."""

from citizens.config import get_settings


def test_the_registered_script_is_a_versioned_loader(client):
    response = client.get("/js/citizens-main.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert "no-store" in response.headers["cache-control"]
    body = response.text
    assert f'encodeURIComponent("{get_settings().app_version}")' in body
    assert "citizens-main.bundle.js?v=" in body and "citizens-main.bundle.css?v=" in body


def test_the_registered_stylesheet_is_a_stub(client):
    response = client.get("/css/citizens-main.css")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/css")
    assert "no-store" in response.headers["cache-control"]
