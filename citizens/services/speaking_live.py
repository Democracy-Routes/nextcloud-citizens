# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Live speaking balance from caption lines (0.7 facilitator).

Some engines label who is speaking as they caption (Deepgram's diarization).
When they do, the lines a table's live source produces carry a `speaker`
index, and this turns the last few minutes of them into an anonymous
distribution — Voice A, Voice B, Voice C — for the facilitator's phone and
the AI facilitator's balance nudge. When the engine does not label speakers
there is nothing here, and the page says so rather than guessing.

Shares are of SPEAKING TIME, measured from each line's start to its end (or
to the next line's start): the engine's guess at who spoke, never a record
of who said what, never a name.
"""

#: how far back the rolling window looks
WINDOW_SECONDS = 300.0
#: below this nothing is said about balance: two lines are not a pattern
MIN_SPEECH_SECONDS = 45.0


def live_balance(lines: list[dict], window_seconds: float = WINDOW_SECONDS) -> dict | None:
    """{voices, shares (percent, descending), largest_percent, seconds} from
    labelled caption lines, or None when the engine labels no speakers or too
    little was said in the window."""
    labelled = [
        line for line in lines
        if line.get("speaker") is not None and not line.get("provisional")
    ]
    if not labelled:
        return None
    latest = max(float(line["t"]) for line in labelled)
    since = latest - window_seconds
    recent = [line for line in labelled if float(line["t"]) >= since]
    recent.sort(key=lambda line: float(line["t"]))
    seconds: dict[int, float] = {}
    for index, line in enumerate(recent):
        start = float(line["t"])
        end = line.get("end")
        if end is None:
            next_start = float(recent[index + 1]["t"]) if index + 1 < len(recent) else start + 3.0
            # a line with no end lasts until the next one starts, capped: a
            # pause is not speech
            end = min(next_start, start + 20.0)
        duration = max(0.0, float(end) - start)
        seconds[int(line["speaker"])] = seconds.get(int(line["speaker"]), 0.0) + duration
    total = sum(seconds.values())
    if total < MIN_SPEECH_SECONDS:
        return None
    shares = sorted((round(100 * value / total) for value in seconds.values()), reverse=True)
    return {
        "voices": len(seconds),
        "shares": shares,
        "largest_percent": shares[0] if shares else 0,
        "seconds": round(total),
        "window_seconds": int(window_seconds),
    }


def engine_labels_speakers(lines: list[dict]) -> bool:
    """Whether this engine is labelling speakers at all (the capability flag)."""
    return any(line.get("speaker") is not None for line in lines)
