# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Layout regressions in the report PDF, asserted on the drawing operations.

The existing renderer test checks the magic bytes and a byte count, which is
why a real report shipped with vertical accent bars running the whole height of
three of its thirteen pages. These read the content streams instead.
"""

import re
import zlib

from citizens.services.report_pdf import render_pdf

A4_HEIGHT_PT = 841.89


def _pages(pdf: bytes) -> list[str]:
    """Each page's decompressed drawing operations, in order."""
    streams = []
    for match in re.finditer(rb"stream\r?\n", pdf):
        body = pdf[match.end() : pdf.find(b"endstream", match.end())]
        try:
            streams.append(zlib.decompress(body).decode("latin-1", "ignore"))
        except zlib.error:
            continue  # a font or an image, not a page
    return [s for s in streams if " m " in s and " l " in s]


def _vertical_bars(page: str) -> list[float]:
    """Heights of the vertical rules on one page (the evidence accent bars)."""
    heights = []
    for x1, y1, x2, y2 in re.findall(
        r"([\d.]+) ([\d.]+) m ([\d.]+) ([\d.]+) l S", page
    ):
        if abs(float(x2) - float(x1)) < 0.5:
            heights.append(abs(float(y2) - float(y1)))
    return heights


def _report(quote: str, quotes_per_finding: int = 5, findings: int = 12, tables: int = 1,
            cross_table: bool = True) -> dict:
    evidence = [
        {"speaker": f"SPEAKER_{i:02d}", "start": float(i * 7), "timestamp": f"0{i}:00",
         "text": quote}
        for i in range(quotes_per_finding)
    ]
    return {
        "assembly": {
            "name": "Bologna Mobility Assembly", "description": "How people move.",
            "language": "en", "participants": 48, "expected_participants": 50, "tables": 10,
        },
        "method": "In-person citizens' assembly.",
        "methodology_note": "AI was used to assist transcription and analysis. " * 12,
        "rounds": [
            {
                "position": 1, "title": "Round 1 - design", "question": "What can improve?",
                "summary": "A summary of the round.",
                "cross_table": [
                    {
                        "type": "proposal", "title": "Across the tables: later buses",
                        "summary": "Several tables asked for later buses.",
                        "support": "", "is_draft": False, "mentioned_table_count": 3,
                        "evidence_removed": False, "evidence": evidence[:1],
                    }
                ] if cross_table else [],
                "tables": [
                    {
                        "table_number": number, "summary": "The table discussed cycle lanes.",
                        "findings": [
                            {
                                "type": "proposal", "title": f"Proposal number {n}",
                                "summary": "A finding that needs supporting evidence. " * 3,
                                "support": "", "is_draft": False, "mentioned_table_count": 0,
                                "evidence_removed": False, "evidence": evidence,
                            }
                            for n in range(findings)
                        ],
                    }
                    for number in range(1, tables + 1)
                ],
            }
        ],
        "include_drafts": False, "published_at": None, "is_final": True,
        "closed_at": "2026-09-04T10:00:00+00:00", "status": "COMPLETE",
        "progress": {"tables_expected": 10, "tables_contributed": 4},
    }


def test_no_accent_bar_spans_a_whole_page():
    """The bar was drawn from a Y captured on the PREVIOUS page.

    When a quote block crossed a page break, get_y() had reset to the top of
    the new page, so the bar was emitted there running almost its full height —
    and the page that actually held the first quotes got none. Measured in a
    real report: 627, 649 and 663pt bars on an 842pt page.
    """
    pdf = render_pdf(_report("A quote long enough to wrap onto several lines. " * 4))

    for number, page in enumerate(_pages(pdf), start=1):
        for height in _vertical_bars(page):
            assert height < A4_HEIGHT_PT * 0.6, (
                f"page {number} has a {height:.0f}pt vertical bar — "
                "an evidence block was split across a page break"
            )


def test_every_page_of_quotes_carries_its_own_bar():
    """The complement: no page should hold quotes with no bar beside them."""
    pdf = render_pdf(_report("A quote long enough to wrap onto several lines. " * 4))

    for number, page in enumerate(_pages(pdf), start=1):
        # a page showing timestamps is a page showing evidence
        if re.search(r"\[0\d:00\]", page) and number > 1:
            assert _vertical_bars(page), f"page {number} shows quotes with no accent bar"


def test_the_methodology_note_does_not_widow_onto_its_own_page():
    """It was drawn after a rule with no measurement, so a long note left two
    orphaned lines on an otherwise empty final page."""
    for findings in range(1, 14):
        pdf = render_pdf(_report("Short but real quote text here.", findings=findings))
        last = _pages(pdf)[-1]
        # the last page must carry more than just the tail of the note
        assert "BT" in last, f"{findings} findings produced an empty final page"


def _footer_markers(pdf_bytes_fn, monkeypatch) -> list[str]:
    """The footer marker ("Table N" or nothing) of every page, in page order,
    captured when each page's footer is drawn."""
    from citizens.services import report_pdf as mod

    markers: list[str] = []
    original = mod._ReportPDF.footer

    def wrapper(self):
        markers.append(self.footer_marker)
        return original(self)

    monkeypatch.setattr(mod._ReportPDF, "footer", wrapper)
    pdf_bytes_fn()
    return markers


def test_each_table_starts_on_a_page_of_its_own(monkeypatch):
    """A ten-table report ran the tables together under 8-pt eyebrows. Now a
    table opens a fresh page with a banner, and the footer names the table
    on every page of it, so the sections are told apart at a glance."""
    markers = _footer_markers(
        lambda: render_pdf(_report("Short but real quote text here.", findings=2, tables=3)),
        monkeypatch,
    )
    tabled = [m for m in markers if m]
    assert tabled == ["Table 1", "Table 2", "Table 3"], markers
    assert markers[0] == "", "the cover carries no table marker"
    # the table pages come after the round's own page(s), never before
    assert markers.index("Table 1") > 0

    one = len(_pages(render_pdf(_report("Short but real quote text here.", findings=2, tables=1))))
    three = len(_pages(render_pdf(_report("Short but real quote text here.", findings=2, tables=3))))
    assert three == one + 2


def test_a_table_running_over_several_pages_keeps_its_marker(monkeypatch):
    markers = _footer_markers(
        lambda: render_pdf(_report("A quote long enough to wrap onto several lines. " * 4,
                                   findings=12, tables=2)),
        monkeypatch,
    )
    tabled = [m for m in markers if m]
    assert tabled.count("Table 1") > 1
    assert tabled == sorted(tabled), "a table's pages are contiguous"


def test_the_next_round_starts_a_clean_page_after_the_table_pages(monkeypatch):
    report = _report("Short but real quote text here.", findings=2, tables=2)
    second = dict(report["rounds"][0], position=2, title="Round 2 - decide")
    report["rounds"].append(second)
    markers = _footer_markers(lambda: render_pdf(report), monkeypatch)
    first_t2 = markers.index("Table 2")
    # after the last table page of round 1 comes round 2's own page, unmarked
    assert markers[first_t2 + 1] == "", markers
    assert markers[first_t2 + 2] == "Table 1", markers


def test_a_round_with_nothing_of_its_own_keeps_its_first_table_on_its_page(monkeypatch):
    """No cross-table findings and no comparison: a page holding only the
    round banner and its question would be waste, so table 1 follows them."""
    report = _report("Short but real quote text here.", findings=2, tables=2, cross_table=False)
    markers = _footer_markers(lambda: render_pdf(report), monkeypatch)
    assert markers == ["Table 1", "Table 2"], markers
    with_cross = _footer_markers(
        lambda: render_pdf(_report("Short but real quote text here.", findings=2, tables=2)),
        monkeypatch,
    )
    assert with_cross == ["", "Table 1", "Table 2"], with_cross


def test_every_page_says_powered_by_democracyroutes(monkeypatch):
    from citizens.services import report_pdf as mod
    from citizens.services.report_text import POWERED_BY

    drawn: list[str] = []
    original = mod._ReportPDF.cell

    def wrapper(self, *a, **k):
        txt = k.get("txt", k.get("text", a[2] if len(a) > 2 else ""))
        if isinstance(txt, str):
            drawn.append(txt)
        return original(self, *a, **k)

    monkeypatch.setattr(mod._ReportPDF, "cell", wrapper)
    pdf = render_pdf(_report("Short but real quote text here.", findings=2, tables=2))
    branded = [t for t in drawn if POWERED_BY in t]
    assert len(branded) == len(_pages(pdf))
    assert any(t.startswith("Bologna Mobility Assembly  ·  Table 2  ·  ") for t in branded), branded
    assert branded[0] == f"Bologna Mobility Assembly  ·  {POWERED_BY}"


def test_the_table_banner_is_drawn_once_per_table(monkeypatch):
    seen = _captured_text(
        lambda: render_pdf(_report("Short but real quote text here.", findings=2, tables=3)),
        monkeypatch,
    )
    assert [t for t in seen if re.fullmatch(r"Table \d+", t)] == ["Table 1", "Table 2", "Table 3"]
    assert seen.count("Table detail") == 1


# Text is deliberately NOT asserted here. The report embeds DejaVu as a CID
# font, so the content stream holds 2-byte glyph ids rather than characters —
# a substring check against it silently passes for any string at all. The
# wording lives in report.py and is tested there, against real strings.


def _captured_text(pdf_bytes_fn, monkeypatch) -> list[str]:
    """Every string the renderer draws, captured before glyph encoding.

    The PDF content stream stores glyph ids, not characters, so a substring
    search over the bytes proves nothing. Spying on the text methods lets us
    assert on what was actually asked to be drawn.
    """
    from citizens.services import report_pdf as mod

    seen: list[str] = []
    for name in ("text_block", "eyebrow", "group_heading", "banner", "badge"):
        original = getattr(mod._ReportPDF, name)

        def wrapper(self, text, *a, __orig=original, **k):
            seen.append(text)
            return __orig(self, text, *a, **k)

        monkeypatch.setattr(mod._ReportPDF, name, wrapper)
    pdf_bytes_fn()
    return seen


def test_the_round_summary_is_drawn_once_not_twice(monkeypatch):
    """It belongs to the Executive summary; repeating it at the head of the
    round section was pure duplication."""
    seen = _captured_text(
        lambda: render_pdf(_report("Short but real quote text here.", findings=2)),
        monkeypatch,
    )
    assert seen.count("A summary of the round.") == 1


def _plenary_pdf_report() -> dict:
    r = _report("Short but real quote text here.", findings=2)
    r["assembly"]["recording_mode"] = "plenary"
    r["rounds"][0]["cross_table"] = list(r["rounds"][0]["tables"][0]["findings"])
    return r


def test_plenary_report_has_no_table_detail_heading(monkeypatch):
    """One group = one table: its findings render directly, with no cross-table
    section and no 'Table detail' / 'Table N' framing."""
    seen = _captured_text(lambda: render_pdf(_plenary_pdf_report()), monkeypatch)
    assert "Table detail" not in seen
    assert not any(t.startswith("Table ") for t in seen)


def test_the_speaking_balance_strip_draws_once_when_voices_exist(monkeypatch):
    report = _report("Short but real quote text here.", findings=2)
    # per table, never per round
    report["rounds"][0]["tables"][0]["speaking_balance"] = {
        "voices": [
            {"label": "A", "seconds": 300, "percent": 70},
            {"label": "B", "seconds": 129, "percent": 30},
        ],
        "total_seconds": 429,
        "from_recording_id": "rec-1",
        "parts": 2,
        "recorder_changed": True,
    }
    seen = _captured_text(lambda: render_pdf(report), monkeypatch)
    assert seen.count("Speaking balance") == 1
    assert any(t.startswith("Voice A — 70%") for t in seen)
    assert any("fullest part only" in t for t in seen)
    # drawn inside the table's section, after its heading
    assert seen.index("Table 1") < seen.index("Speaking balance")


def test_no_strip_without_diarized_voices(monkeypatch):
    seen = _captured_text(
        lambda: render_pdf(_report("Short but real quote text here.", findings=2)),
        monkeypatch,
    )
    assert "Speaking balance" not in seen


def _italian_report() -> dict:
    report = _report("Una citazione abbastanza lunga da contare.", findings=2)
    report["assembly"]["language"] = "it"
    report["rounds"][0]["title"] = "Round 1"  # the untouched English pre-fill
    report["rounds"][0]["cross_table"] = [
        {
            "type": "proposal", "title": "Autobus serali", "summary": "Più corse la sera.",
            "support": "", "is_draft": True, "mentioned_table_count": 3,
            "evidence_removed": False,
            "evidence": [
                {"table_number": 2, "speaker": "", "timestamp": "02:14",
                 "text": "L'ultimo autobus parte troppo presto."},
            ],
        }
    ]
    report["rounds"][0]["tables"][0]["speaking_balance"] = {
        "voices": [
            {"label": "A", "seconds": 300, "percent": 70},
            {"label": "Others", "seconds": 129, "percent": 30},
        ],
        "total_seconds": 429, "from_recording_id": "rec-1",
    }
    return report


def test_an_italian_report_is_drawn_in_italian(monkeypatch):
    """Every heading, badge and note around the model's Italian text is
    Italian too; the generated-on date is written the Italian way."""
    rendered: list[bytes] = []
    seen = _captured_text(lambda: rendered.append(render_pdf(_italian_report())), monkeypatch)
    assert rendered[0].startswith(b"%PDF")

    assert "RAPPORTO FINALE · chiuso il 2026-09-04" in seen
    assert "4 tavoli su 10 hanno contribuito a questo rapporto" in seen
    assert any(
        re.fullmatch(r"\d{1,2} [a-zà]+ \d{4} · 48 partecipanti \(previsti 50\) · 10 tavoli · IT", t)
        for t in seen
    ), "the cover meta line should carry an Italian date"
    assert "Metodo" in seen
    assert "Sintesi esecutiva" in seen
    assert "Sessione 1" in seen  # section banner and executive summary heading
    assert "Equilibrio degli interventi" in seen
    assert any(t.startswith("Voce A — 70%") for t in seen)
    assert any(t.startswith("Altri — 30%") for t in seen)
    assert "Proposte" in seen  # group heading
    assert "Proposta" in seen  # badge
    assert "bozza — non revisionata" in seen
    assert "Menzionato in 3 tavoli" in seen
    assert any(t.startswith("Tavolo 2 · [02:14] Partecipante:") for t in seen)
    assert "Dettaglio per tavolo" in seen
    assert "Tavolo 1" in seen

    for english in (
        "Assembly Report", "FINAL REPORT", "Method", "Executive summary", "Round 1", "Session 1",
        "Speaking balance", "Proposals", "Proposal", "draft — not reviewed", "Table detail",
        "Table 1", "Others — 30%",
    ):
        assert english not in seen, english
    assert not any(t.startswith("Table ") or t.startswith("Voice ") for t in seen)


def test_an_italian_report_lays_out_like_an_english_one():
    """Longer Italian labels must not break the page-keeping arithmetic."""
    pdf = render_pdf(_italian_report())
    for number, page in enumerate(_pages(pdf), start=1):
        for height in _vertical_bars(page):
            assert height < A4_HEIGHT_PT * 0.6, f"page {number}: {height:.0f}pt bar"


def test_a_session_with_an_objective_still_renders_when_only_two_dejavu_faces_exist():
    """The objective line is italic. fonts-dejavu-core ships DejaVuSans and
    DejaVuSans-Bold only, and an italic style that is not registered is an
    FPDFException — which turned the report PDF of every assembly whose
    sessions had an objective into a 500 (found by the 2026-10-12 rehearsal)."""
    from citizens.services.report_pdf import render_pdf

    report = _report("A quotation long enough to count as evidence here.")
    report["rounds"][0]["objective"] = "Three concrete problems"
    assert render_pdf(report).startswith(b"%PDF")
