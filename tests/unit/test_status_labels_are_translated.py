# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every state the backend can produce must have a label a person can read.

CzStatusPill used to render the database enum with its underscores swapped for
spaces, so a facilitator watching an event read "waiting for chunks" and "audio
invalid" — internal vocabulary, in English, describing something they might
have to act on. Worse, it degraded silently: adding a state to the Python state
machine produced a new piece of jargon on screen and nothing failed.

This test is the link between the two languages. It reads the states Python
actually declares and asserts each has an entry in the frontend catalogue, so
adding one to the state machine without naming it is a build failure rather
than something a facilitator discovers mid-assembly.
"""

import json
import pathlib

import pytest

from citizens.db.models.findings import FINDING_STATUSES
from citizens.services.recording_states import ALLOWED_TRANSITIONS

ROOT = pathlib.Path(__file__).resolve().parents[2]
CATALOGUE = ROOT / "frontend" / "src" / "i18n"


def _labels(locale: str) -> dict:
    return json.loads((CATALOGUE / f"{locale}.json").read_text(encoding="utf-8")).get("state", {})


def _recording_states() -> set[str]:
    """Every state a recording can be in: the keys, plus every target."""
    states = set(ALLOWED_TRANSITIONS)
    for targets in ALLOWED_TRANSITIONS.values():
        states |= targets
    return states


@pytest.mark.parametrize("locale", ["en", "it"])
def test_every_recording_state_has_a_label(locale):
    missing = sorted(_recording_states() - set(_labels(locale)))
    assert not missing, (
        f"these recording states would render as raw database enums in {locale}: "
        + ", ".join(missing)
        + f"\nAdd them to frontend/src/i18n/{locale}.json under \"state\"."
    )


@pytest.mark.parametrize("locale", ["en", "it"])
def test_every_finding_status_has_a_label(locale):
    missing = sorted(set(FINDING_STATUSES) - set(_labels(locale)))
    assert not missing, f"finding statuses with no {locale} label: {', '.join(missing)}"


# Words that mean something to this codebase and nothing to a facilitator.
# A lower-cased enum is often a perfectly good label — "draft", "recording",
# "approved" need no improvement — so the thing worth testing is not that the
# label differs from the enum, but that it does not leak internal vocabulary.
INTERNAL_VOCABULARY = ("chunk", "payload", "enum", "null", "json", "sha")


@pytest.mark.parametrize("locale", ["en", "it"])
def test_no_label_uses_internal_vocabulary(locale):
    """"waiting for chunks" was on screen during every upload. A chunk is an
    implementation detail of how the phone talks to the server; the person
    reading it needs to know the recording has not all arrived yet."""
    offenders = [
        f"{state} → {label!r}"
        for state, label in _labels(locale).items()
        if any(word in label.lower() for word in INTERNAL_VOCABULARY)
    ]
    assert not offenders, (
        "these labels expose internal vocabulary to the organizer: "
        + ", ".join(sorted(offenders))
    )
