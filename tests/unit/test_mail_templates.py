# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The invitation and reset mail catalogues: same keys and placeholders in every language."""

import string

import pytest

from citizens.config import get_settings
from citizens.services import mail

LANGUAGES = ["en", "it", "de", "fr", "es"]


@pytest.fixture
def standalone_env(monkeypatch):
    monkeypatch.setenv("CITIZENS_MODE", "standalone")
    monkeypatch.setenv("CITIZENS_PUBLIC_URL", "https://citizens.test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


@pytest.mark.parametrize("lang", LANGUAGES)
def test_catalogue_matches_english(lang):
    english = mail._TEXT["en"]
    strings = mail._TEXT[lang]
    assert set(strings) == set(english)
    for key, value in strings.items():
        assert value.strip(), f"{lang}.{key} is empty"
        assert _placeholders(value) == _placeholders(english[key]), f"{lang}.{key} placeholders"


@pytest.mark.parametrize("lang", LANGUAGES)
def test_render_invite(standalone_env, lang):
    subject, body = mail.render("invite", lang, "Anna", "tok", 168)
    link = "https://citizens.test/?set-password=tok"
    assert "Anna" in body
    assert "citizens.test" in subject and "citizens.test" in body
    assert link in body
    assert f"\n\n{link}\n\n" in body
    assert "tok" not in mail.redact(body)
