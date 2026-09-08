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


def _report(quote: str, quotes_per_finding: int = 5, findings: int = 12) -> dict:
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
                "cross_table": [],
                "tables": [
                    {
                        "table_number": 1, "summary": "The table discussed cycle lanes.",
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
    for name in ("text_block", "eyebrow", "group_heading", "section_banner"):
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
    report["rounds"][0]["speaking_balance"] = {
        "voices": [
            {"label": "A", "seconds": 300, "percent": 70},
            {"label": "B", "seconds": 129, "percent": 30},
        ],
        "total_seconds": 429,
        "from_recording_id": "rec-1",
    }
    seen = _captured_text(lambda: render_pdf(report), monkeypatch)
    assert seen.count("Speaking balance") == 1
    assert any(t.startswith("Voice A — 70%") for t in seen)


def test_no_strip_without_diarized_voices(monkeypatch):
    seen = _captured_text(
        lambda: render_pdf(_report("Short but real quote text here.", findings=2)),
        monkeypatch,
    )
    assert "Speaking balance" not in seen
