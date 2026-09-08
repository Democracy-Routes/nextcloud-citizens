# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wording of a report: how rounds are named, and what the cover claims.

Asserted against the Markdown, which is plain text. The PDF embeds DejaVu as a
CID font, so its content stream holds glyph ids rather than characters and a
substring check against it passes for anything at all.
"""

from citizens.services.report import render_markdown, round_heading


def _report(participants: int = 48, title: str = "Design") -> dict:
    return {
        "assembly": {
            "name": "Bologna", "description": "", "language": "en",
            "participants": participants, "expected_participants": 50, "tables": 10,
        },
        "method": "In-person citizens' assembly.",
        "methodology_note": "AI was used to assist transcription and analysis.",
        "rounds": [
            {
                "position": 1, "title": title, "question": "What can improve?",
                "summary": "", "cross_table": [], "tables": [],
            }
        ],
        "include_drafts": False, "published_at": None, "is_final": True,
        "closed_at": "2026-09-04T10:00:00+00:00", "status": "COMPLETE",
        "progress": {"tables_expected": 10, "tables_contributed": 4},
    }


class TestRoundHeading:
    """Both round-creation paths pre-fill the title with "Round N", so an
    organizer who edits it to "Round 1 - design" used to get
    "Round 1 — Round 1 - design" on every screen and in every export."""

    def test_a_title_repeating_the_round_number_is_used_alone(self):
        assert round_heading(1, "Round 1 - design") == "Round 1 - design"

    def test_the_untouched_default_is_not_doubled_either(self):
        assert round_heading(2, "Round 2") == "Round 2"

    def test_a_real_title_still_gets_its_number(self):
        assert round_heading(3, "Mobility") == "Round 3 — Mobility"

    def test_an_empty_title_falls_back_to_the_number(self):
        assert round_heading(4, "") == "Round 4"
        assert round_heading(4, "   ") == "Round 4"

    def test_a_bare_number_prefix_counts_as_the_round_number(self):
        assert round_heading(5, "5. Housing") == "5. Housing"

    def test_a_different_number_is_not_mistaken_for_this_round(self):
        # "Round 2" as the title of round 1 is a mistake, but not ours to hide
        assert round_heading(1, "Round 2 - design") == "Round 1 — Round 2 - design"

    def test_a_title_merely_starting_with_the_word_round(self):
        assert round_heading(1, "Rounding up the evidence") == "Round 1 — Rounding up the evidence"


class TestCoverParticipants:
    """The count is a live count of the organizer's roster, and recording a
    table creates no roster entry — so an assembly that ran perfectly well
    announced "0 participants (expected 50)" on the cover of its final report."""

    def test_a_roster_is_reported_when_there_is_one(self):
        assert "- Participants: 48 (expected 50)" in render_markdown(_report(participants=48))

    def test_no_roster_says_nothing_rather_than_zero(self):
        markdown = render_markdown(_report(participants=0))

        assert "Participants" not in markdown
        # the rest of the cover is unaffected
        assert "- Tables: 10" in markdown
        assert "- Language: EN" in markdown


def _finding(fid: str, title: str, type_: str = "proposal") -> dict:
    return {
        "id": fid, "type": type_, "title": title, "summary": "A neutral description.",
        "is_draft": False, "mentioned_table_count": 0, "evidence": [],
        "evidence_removed": False,
    }


def _plenary_report() -> dict:
    r = _report()
    r["assembly"]["recording_mode"] = "plenary"
    r["rounds"][0]["summary"] = "The group discussed transport."
    r["rounds"][0]["tables"] = [
        {"table_number": 1, "summary": "The group discussed transport.",
         "analyzed": True,
         "findings": [_finding("f1", "Later evening buses"),
                      _finding("f2", "Safer cycle lanes", "concern")]},
    ]
    return r


class TestPlenaryReportHasNoDuplication:
    """A plenary run is one group. Rendering its findings once — with no
    cross-table section and no 'Table 1' framing — is the whole point of the
    de-duplication pass."""

    def test_each_finding_appears_exactly_once(self):
        md = render_markdown(_plenary_report())
        assert md.count("Later evening buses") == 1
        assert md.count("Safer cycle lanes") == 1

    def test_no_across_all_tables_or_table_heading(self):
        md = render_markdown(_plenary_report())
        assert "Across all tables" not in md
        assert "### Table 1" not in md

    def test_the_round_summary_still_shows_once(self):
        md = render_markdown(_plenary_report())
        assert md.count("The group discussed transport.") == 1


def _balanced_report() -> dict:
    r = _report()
    r["rounds"][0]["speaking_balance"] = {
        "voices": [
            {"label": "A", "seconds": 750, "percent": 60},
            {"label": "B", "seconds": 375, "percent": 30},
            {"label": "Others", "seconds": 125, "percent": 10},
        ],
        "total_seconds": 1250,
        "from_recording_id": "rec-1",
    }
    return r


class TestSpeakingBalanceInReport:
    """The Analysis tab's talk-time chart, ported to the exports — only when
    diarization actually produced distinct voices. One voice means the whole
    recording was a single label (no diarization) and says nothing."""

    def test_voices_and_caption_render(self):
        md = render_markdown(_balanced_report())
        assert "Speaking balance" in md
        assert "- Voice A — 60% (12:30)" in md
        assert "- Others — 10%" in md
        assert "not identified by name" in md

    def test_a_single_voice_is_not_printed(self):
        r = _balanced_report()
        r["rounds"][0]["speaking_balance"]["voices"] = [
            {"label": "A", "seconds": 100, "percent": 100},
        ]
        assert "Speaking balance" not in render_markdown(r)

    def test_an_old_snapshot_without_the_key_still_renders(self):
        # frozen final reports predate the field; .get() must carry them
        assert "Speaking balance" not in render_markdown(_report())
