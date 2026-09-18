# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wording of a report: how rounds are named, and what the cover claims.

Asserted against the Markdown, which is plain text. The PDF embeds DejaVu as a
CID font, so its content stream holds glyph ids rather than characters and a
substring check against it passes for anything at all.
"""

import re
from datetime import date
from string import Formatter

import pytest

from citizens.db.models import Assembly, Finding, Recording, Round, Table
from citizens.db.models.findings import FINDING_TYPES
from citizens.db.session import session_scope
from citizens.services.report import (
    METHODOLOGY_NOTE,
    TYPE_LABELS,
    TYPE_LABELS_SINGULAR,
    build_report,
    render_markdown,
    round_heading,
)
from citizens.services.report_pdf import render_pdf
from citizens.services.report_text import (
    CATALOGUE,
    TYPE_ORDER,
    format_date,
    month_name,
    normalize_language,
    text,
    type_labels,
    type_labels_singular,
)


def _report(participants: int = 48, title: str = "Design", language: str = "en") -> dict:
    return {
        "assembly": {
            "name": "Bologna", "description": "", "language": language,
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


# ---------------------------------------------------------------------------
# Localized wording (report_text.py)
# ---------------------------------------------------------------------------


def _rich_report(language: str = "en") -> dict:
    """Every kind of line the Markdown renderer can print, in one report."""
    return {
        "assembly": {
            "name": "Bologna", "description": "How people move.", "language": language,
            "participants": 48, "expected_participants": 50, "tables": 10,
        },
        "method": "In-person citizens' assembly.",
        "methodology_note": "AI was used to assist transcription and analysis.",
        "rounds": [
            {
                "position": 1, "title": "Design", "question": "What can improve?",
                "summary": "Tables focused on buses.",
                "cross_table": [
                    {
                        "id": "c1", "type": "proposal", "title": "Later buses",
                        "summary": "Several tables asked for later buses.",
                        "is_draft": False, "mentioned_table_count": 4,
                        "evidence_removed": False,
                        "evidence": [
                            {"table_number": 2, "speaker": "", "timestamp": "02:14",
                             "text": "The last bus leaves too early."},
                        ],
                    },
                    {
                        "id": "c2", "type": "weird", "title": "Unclassified",
                        "summary": "Something else.", "is_draft": True,
                        "mentioned_table_count": 0, "evidence_removed": False,
                        "evidence": [],
                    },
                ],
                "tables": [
                    {
                        "table_number": 1, "summary": "The table discussed commuting.",
                        "findings": [
                            {
                                "id": "t1", "type": "concern", "title": "Unsafe lanes",
                                "summary": "Cycle lanes feel unsafe.", "is_draft": False,
                                "mentioned_table_count": 0, "evidence_removed": True,
                                "evidence": [],
                            },
                            {
                                "id": "t2", "type": "new_idea", "title": "Cargo bikes",
                                "summary": "A shared fleet.", "is_draft": False,
                                "mentioned_table_count": 0, "evidence_removed": False,
                                "evidence": [
                                    {"speaker": "SPEAKER_02", "timestamp": "11:02",
                                     "text": "Why not cargo bikes?"},
                                ],
                            },
                        ],
                    },
                    {"table_number": 2, "summary": "", "findings": []},
                ],
            },
            {
                "position": 2, "title": "Round 2", "question": "", "summary": "",
                "cross_table": [], "tables": [],
            },
        ],
        "include_drafts": True, "published_at": None, "is_final": False,
        "closed_at": None, "status": "IN_PROGRESS",
        "progress": {"tables_expected": 10, "tables_contributed": 4, "tables_complete": 3},
    }


# The Markdown the renderer produced for _rich_report("en") BEFORE the wording
# moved into report_text.py. English output must not move by a byte.
EXPECTED_ENGLISH = """# Bologna — Assembly Report

**INTERIM REPORT** — 3 of 10 tables have completed all rounds

How people move.

- Tables contributing: 4 of 10
- Participants: 48 (expected 50)
- Tables: 10
- Language: EN

## Method

In-person citizens' assembly.

## Round 1 — Design

> What can improve?

*AI summary:* Tables focused on buses.

### Across all tables

#### Proposals

**Proposal: Later buses**

Mentioned at 4 table(s).

Several tables asked for later buses.

> Table 2 · [02:14] Speaker: “The last bus leaves too early.”

#### Other findings

**weird: Unclassified** *(DRAFT — not yet reviewed)*

Something else.

### Table 1

*AI summary:* The table discussed commuting.

**Concern: Unsafe lanes**

Cycle lanes feel unsafe.

_Evidence removed with the transcript._

**Emerging idea: Cargo bikes**

A shared fleet.

> [11:02] SPEAKER_02: “Why not cargo bikes?”

## Round 2

_No findings for this round yet._

---

_AI was used to assist transcription and analysis._
"""


class TestEnglishWordingIsUnchanged:
    def test_the_markdown_matches_the_pre_localization_output(self):
        assert render_markdown(_rich_report("en")) == EXPECTED_ENGLISH

    def test_an_unknown_language_reads_english(self):
        # the cover still prints the code the assembly was given
        expected = EXPECTED_ENGLISH.replace("- Language: EN", "- Language: XX")
        assert render_markdown(_rich_report("xx")) == expected

    def test_module_constants_are_the_english_catalogue(self):
        assert TYPE_LABELS == type_labels("en")
        assert TYPE_LABELS_SINGULAR == type_labels_singular("en")
        assert TYPE_LABELS["disagreement"] == "Points of divergence"
        assert TYPE_LABELS_SINGULAR["new_idea"] == "Emerging idea"
        assert METHODOLOGY_NOTE.startswith("AI was used to assist")
        assert "not a measure of participant support" in METHODOLOGY_NOTE


class TestCatalogueParity:
    """Italian is the language of next week's assembly: it must cover every
    key English has, with real text, using the same placeholders."""

    def test_italian_has_every_english_key(self):
        assert set(CATALOGUE["en"]) - set(CATALOGUE["it"]) == set()

    def test_no_language_invents_keys_english_lacks(self):
        for code, entries in CATALOGUE.items():
            assert set(entries) <= set(CATALOGUE["en"]), code

    def test_no_italian_value_is_empty(self):
        for key, value in CATALOGUE["it"].items():
            assert value.strip(), key

    def test_no_italian_value_is_left_in_english(self):
        for key, value in CATALOGUE["it"].items():
            # the placeholders-only entries ("{count} …") can legitimately
            # coincide; every worded entry must differ from the English
            if key == "date_format":
                continue
            assert value != CATALOGUE["en"][key], key

    def test_placeholders_match_the_english_original(self):
        def fields(template: str) -> set[str]:
            return {name for _, name, _, _ in Formatter().parse(template) if name}

        for code, entries in CATALOGUE.items():
            for key, value in entries.items():
                assert fields(value) == fields(CATALOGUE["en"][key]), f"{code}:{key}"

    def test_the_type_order_is_the_finding_vocabulary(self):
        assert set(TYPE_ORDER) == set(FINDING_TYPES)
        for type_ in TYPE_ORDER:
            assert f"type_plural.{type_}" in CATALOGUE["en"]
            assert f"type_singular.{type_}" in CATALOGUE["en"]

    def test_the_italian_methodology_note_keeps_the_support_caveat(self):
        note = text("it", "methodology_note")
        assert "«Menzionato in N tavoli»" in note
        assert "non è una misura del sostegno dei partecipanti" in note


class TestLookup:
    def test_a_missing_key_falls_back_to_english(self):
        # German has only its dates; everything else reads English
        assert text("de", "assembly_report") == "Assembly Report"
        assert text("fr", "type_plural.proposal") == "Proposals"

    def test_an_unknown_language_reads_english(self):
        assert text("xx", "assembly_report") == "Assembly Report"
        assert text(None, "assembly_report") == "Assembly Report"
        assert text("", "assembly_report") == "Assembly Report"

    def test_region_and_case_are_ignored(self):
        assert normalize_language("it-IT") == "it"
        assert normalize_language("IT") == "it"
        assert normalize_language("it_IT") == "it"
        assert text("it-IT", "assembly_report") == "Rapporto dell'assemblea"

    def test_an_unknown_key_is_a_programming_error(self):
        with pytest.raises(KeyError):
            text("it", "no_such_key")

    def test_placeholders_are_filled(self):
        assert text("it", "table", number=3) == "Tavolo 3"
        assert text("en", "tables_contributing", contributed=4, expected=10) == (
            "Tables contributing: 4 of 10"
        )

    def test_type_labels_per_language(self):
        assert type_labels("it")["disagreement"] == "Punti di divergenza"
        assert type_labels_singular("it")["minority_position"] == "Posizione di minoranza"
        assert list(type_labels("it")) == list(TYPE_ORDER)


class TestDates:
    def test_english_matches_the_old_strftime_format(self):
        # strftime("%-d %B %Y") in the C locale: day without a leading zero
        assert format_date("en", date(2026, 9, 4)) == "4 September 2026"

    def test_month_names(self):
        assert month_name("it", 9) == "settembre"
        assert month_name("de", 3) == "März"
        assert month_name("xx", 1) == "January"

    def test_each_language_writes_its_own_date(self):
        when = date(2026, 9, 18)
        assert format_date("it", when) == "18 settembre 2026"
        assert format_date("de", when) == "18. September 2026"
        assert format_date("fr", when) == "18 septembre 2026"
        assert format_date("es", when) == "18 de septiembre de 2026"


class TestRoundHeadingInItalian:
    def test_an_empty_title_is_the_localized_default(self):
        assert round_heading(3, "", "it") == "Turno 3"

    def test_the_untouched_english_prefill_is_translated(self):
        # both round-creation paths pre-fill "Round N" whatever the language
        assert round_heading(2, "Round 2", "it") == "Turno 2"

    def test_a_real_title_gets_the_localized_number(self):
        assert round_heading(1, "Mobilità", "it") == "Turno 1 — Mobilità"

    def test_a_title_already_naming_the_turno_is_used_alone(self):
        assert round_heading(1, "Turno 1 - mobilità", "it") == "Turno 1 - mobilità"
        assert round_heading(1, "turno 1: casa", "it") == "turno 1: casa"

    def test_an_organizers_english_title_is_printed_as_written(self):
        assert round_heading(1, "Round 1 - design", "it") == "Round 1 - design"

    def test_a_bare_number_prefix_still_counts(self):
        assert round_heading(5, "5. Casa", "it") == "5. Casa"

    def test_english_is_untouched_by_the_language_argument(self):
        assert round_heading(2, "Round 2", "en") == "Round 2"
        assert round_heading(3, "Mobility", "en") == "Round 3 — Mobility"


class TestItalianMarkdown:
    """The model already writes findings in Italian; the frame around them
    must be Italian too, or the report reads as a half-translated form."""

    def test_the_cover(self):
        md = render_markdown(_rich_report("it"))
        assert md.startswith("# Bologna — Rapporto dell'assemblea\n")
        assert "**RAPPORTO PROVVISORIO** — 3 tavoli su 10 hanno completato tutti i turni" in md
        assert "- Tavoli che hanno contribuito: 4 su 10" in md
        assert "- Partecipanti: 48 (previsti 50)" in md
        assert "- Tavoli: 10" in md
        assert "- Lingua: IT" in md
        assert "## Metodo" in md

    def test_a_final_report(self):
        report = _report(language="it")
        md = render_markdown(report)
        assert "**RAPPORTO FINALE** — chiuso il 2026-09-04" in md
        assert "FINAL REPORT" not in md

    def test_rounds_and_tables(self):
        md = render_markdown(_rich_report("it"))
        assert "## Turno 1 — Design" in md
        assert "## Turno 2\n" in md  # the untouched "Round 2" pre-fill
        assert "*Sintesi IA:* Tables focused on buses." in md
        assert "### In tutti i tavoli" in md
        assert "### Tavolo 1" in md
        assert "_Ancora nessun risultato per questo turno._" in md

    def test_findings(self):
        md = render_markdown(_rich_report("it"))
        assert "#### Proposte" in md
        assert "**Proposta: Later buses**" in md
        assert "Menzionato in 4 tavoli." in md
        assert "#### Altri risultati" in md
        assert "*(BOZZA — non ancora revisionata)*" in md
        assert "**Preoccupazione: Unsafe lanes**" in md
        assert "**Idea emergente: Cargo bikes**" in md
        assert "_Prove rimosse con la trascrizione._" in md

    def test_evidence_lines(self):
        md = render_markdown(_rich_report("it"))
        # the table label and the anonymous-speaker fallback are both words
        assert "> Tavolo 2 · [02:14] Partecipante: “The last bus leaves too early.”" in md
        # a real speaker label is data, printed as is
        assert "> [11:02] SPEAKER_02: “Why not cargo bikes?”" in md

    def test_one_table_is_singular(self):
        report = _rich_report("it")
        report["rounds"][0]["cross_table"][0]["mentioned_table_count"] = 1
        assert "Menzionato in 1 tavolo." in render_markdown(report)

    def test_speaking_balance(self):
        report = _balanced_report()
        report["assembly"]["language"] = "it"
        md = render_markdown(report)
        assert "**Equilibrio degli interventi**" in md
        assert "- Voce A — 60% (12:30)" in md
        assert "- Altri — 10% (02:05)" in md
        assert "*Voci rilevate, non identificate per nome" in md

    def test_plenary_groups_are_italian(self):
        report = _plenary_report()
        report["assembly"]["language"] = "it"
        md = render_markdown(report)
        assert "### Proposte" in md
        assert "### Preoccupazioni emerse" in md
        assert "In tutti i tavoli" not in md

    def test_no_english_frame_survives(self):
        md = render_markdown(_rich_report("it"))
        for english in (
            "Assembly Report", "INTERIM REPORT", "Tables contributing", "Participants:",
            "Language:", "## Method", "Round 1", "AI summary", "Across all tables",
            "### Table", "table(s)", "DRAFT", "Speaker:", "Evidence removed",
            "No findings", "Other findings", "Proposals",
        ):
            assert english not in md, english


def _seed_italian_assembly(session) -> str:
    assembly = Assembly(name="Assemblea di Bologna", created_by="tester", language="it",
                        default_table_count=1)
    session.add(assembly)
    session.flush()
    round_ = Round(assembly_id=assembly.id, position=1, title="Round 1", question="Cosa migliorare?")
    session.add(round_)
    session.flush()
    table = Table(round_id=round_.id, number=1)
    session.add(table)
    session.flush()
    recording = Recording(
        assembly_id=assembly.id, round_id=round_.id, table_id=table.id,
        table_number=1, state="READY_FOR_REVIEW",
    )
    session.add(recording)
    session.add(Finding(
        assembly_id=assembly.id, round_id=round_.id, table_id=table.id,
        scope="table", type="proposal", title="Autobus serali", summary="Più corse la sera.",
        status="APPROVED",
    ))
    session.flush()
    return assembly.id


class TestBuildReportInItalian:
    """build_report() is where the payload's own wording — the method
    sentence, the methodology note, the per-finding label — is fixed, and
    the frozen final report keeps whatever it said."""

    def test_the_payload_carries_italian_wording(self, database):
        with session_scope() as session:
            assembly_id = _seed_italian_assembly(session)
            report = build_report(session, session.get(Assembly, assembly_id))

        assert report["assembly"]["language"] == "it"
        assert report["method"].startswith("Assemblea dei cittadini in presenza")
        assert "distinzione delle voci" not in report["method"]  # no speaker labels
        assert report["methodology_note"].startswith("L'IA è stata utilizzata")
        finding = report["rounds"][0]["tables"][0]["findings"][0]
        assert finding["type"] == "proposal"
        assert finding["type_label"] == "Proposta"
        assert report["rounds"][0]["heading"].startswith("Turno 1"), report["rounds"][0]

    def test_both_renderers_take_the_payload(self, database):
        with session_scope() as session:
            assembly_id = _seed_italian_assembly(session)
            report = build_report(session, session.get(Assembly, assembly_id))

        md = render_markdown(report)
        assert "# Assemblea di Bologna — Rapporto dell'assemblea" in md
        assert "## Turno 1\n" in md
        assert "**Proposta: Autobus serali**" in md
        assert re.search(r"^_L'IA è stata utilizzata.*_$", md, re.MULTILINE)
        assert render_pdf(report).startswith(b"%PDF")

    def test_an_english_assembly_labels_in_english(self, database):
        with session_scope() as session:
            assembly_id = _seed_italian_assembly(session)
            assembly = session.get(Assembly, assembly_id)
            assembly.language = "en"
            session.flush()
            report = build_report(session, assembly)

        finding = report["rounds"][0]["tables"][0]["findings"][0]
        assert finding["type_label"] == "Proposal"
        assert report["methodology_note"] == METHODOLOGY_NOTE
        assert report["method"].startswith("In-person citizens' assembly")
