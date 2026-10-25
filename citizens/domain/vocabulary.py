# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Product vocabulary versus the names in the schema — the bridge for 0.7.

Citizens 1.0 talks about:

    Assembly   (optional) an organized event: several Sessions, participants,
               a full report
    Session    one question discussed at one or more tables; the unit a user
               starts from — on its own, or inside an Assembly
    Table      one discussion within a Session, numbered and coloured
    Recorder   a phone recording a Table (one or more per Table)

The database, the recorder's upload path, the analysis, the reports and most
tests still spell the Session as `Round` (`rounds`, `round_id`, `/rounds/{id}`)
and a standalone Session as a container `Assembly(kind="session")` holding one
round. That is deliberate: `round_id` is wired through recording, transcription,
analysis and ~1,600 references, and a global rename would destabilise the one
part of the app that must never wobble. So:

- **new product and API surfaces say Session** — `POST /sessions`,
  `GET /sessions/{id}`, `session_id` in their payloads, "Session" in the
  organizer's labels and the phone's strings;
- **existing routes, columns and internals keep Round** — `/rounds/{id}`
  stays, `Round` the model stays, `round_id` in payloads the recorder already
  reads stays — and a `session_id` in a Session payload IS a round id;
- **`recorder_sessions` is a different thing**: a phone's bearer session.
  Nothing in recorder code may use a bare `session_id` to mean a Session;
  that word there already means the device's authentication.

Reports still print "Round N" headings (`report.round_heading`); moving the
report vocabulary is a later step, with its own fixtures.

`SESSION_TERMS` is the one place that states the mapping, for code that needs
to translate between the two (the Session API adapter in services/sessions.py).
"""

#: product term → the schema/legacy name it is stored under
SESSION_TERMS = {
    "session": "round",
    "session_id": "round_id",
    "sessions": "rounds",
    "assembly": "assembly",
    "table": "table",
    "recorder": "recorder_session",
}


def legacy_name(term: str) -> str:
    """The schema name behind a product term ("session" → "round")."""
    return SESSION_TERMS.get(term, term)
