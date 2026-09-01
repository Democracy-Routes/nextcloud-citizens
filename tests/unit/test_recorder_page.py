# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The page citizens open on their own phones.

Two things it must not do: claim a language it cannot know, and stop people
enlarging the text.
"""

from citizens.api.recorder_page import RECORDER_HTML


def test_the_page_does_not_hardcode_a_language():
    """The invite token lives in the URL fragment and never reaches the server,
    so this page cannot know which assembly — or which language — it is for.
    Declaring English told every screen reader the Italian text was English."""
    assert '<html lang="en">' not in RECORDER_HTML
    assert '<html lang="">' in RECORDER_HTML


def test_the_viewport_allows_zooming():
    """WCAG 1.4.4. The people most likely to need to enlarge the round's
    question are the least likely to know how to defeat user-scalable=no."""
    import re

    # the meta tag itself, not the whole document: the comment above it names
    # the attributes precisely so the reason is not lost
    match = re.search(
        r'<meta name="viewport" content="([^"]*)"', RECORDER_HTML.replace("\\\n", "")
    )
    assert match, "the viewport meta tag is missing"
    viewport = match.group(1)
    assert "user-scalable=no" not in viewport
    assert "maximum-scale" not in viewport
    assert "width=device-width" in viewport


def test_the_boot_placeholder_carries_no_untranslatable_text():
    """It is rendered before the bundle — and so before any catalogue — exists,
    at a moment when the server still does not know the room's language."""
    assert "Loading recorder" not in RECORDER_HTML
    assert "boot-spinner" in RECORDER_HTML


def test_the_bundle_failure_message_survives():
    """The one string that cannot be translated: if the bundle did not load,
    neither did the translations. It must still say something."""
    assert "Failed to load the recorder application" in RECORDER_HTML
