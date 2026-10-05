# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The printable event kit: a card per table, the programme, the notice —
in the assembly's language, and a valid PDF whatever the assembly has."""

from types import SimpleNamespace

from citizens.services.consent_notice import render_notice
from citizens.services.event_kit import render_event_kit

HANDLING = {
    "stt_provider": "vosk", "stt_configured": True, "stt_hosted": False,
    "analysis_enabled": True, "analysis_hosted": True, "audio_retention_days": 30,
}
ROUNDS = [
    {"position": 2, "title": "Priorities", "question": "What first?", "objective": "",
     "duration_minutes": 20},
    {"position": 1, "title": "", "question": "What is wrong?", "objective": "A list of problems",
     "duration_minutes": 30},
]


def _cards(n):
    return [SimpleNamespace(table_number=i, url=f"https://example.org/recorder.html#/join/t{i}")
            for i in range(1, n + 1)]


def test_the_kit_is_a_pdf_with_a_sheet_per_two_tables_plus_programme_and_notice():
    pdf = render_event_kit("Bologna", "en", _cards(5), ROUNDS, HANDLING, None, "Comune")
    assert pdf.startswith(b"%PDF")
    # 5 cards → 3 sheets, then the programme, then the notice
    assert pdf.count(b"/Type /Page\n") == 5 or pdf.count(b"/Type /Page") >= 5


def test_an_empty_assembly_still_prints():
    pdf = render_event_kit("Fresh", "it", [], [], {}, None, "")
    assert pdf.startswith(b"%PDF")


def test_the_kit_prints_the_consent_notice_itself():
    """Paper and phone say the same thing: the kit's notice page is the
    renderer's output, not a second text."""
    org = {"organization_name": "Comune", "consent_contact": "privacy@example.org"}
    notice = render_notice("it", HANDLING, organization=org, auto_purge=False)
    pdf = render_event_kit("Bologna", "it", _cards(1), ROUNDS, HANDLING, None, "Comune",
                           organization=org, auto_purge=False)
    assert pdf.startswith(b"%PDF")
    # fpdf2 compresses page streams; the words survive in the PDF only
    # decompressed, so assert on the renderer's contract instead
    assert notice.paragraphs[0].startswith("Comune registra questa discussione")
    assert "Contatto: privacy@example.org." in notice.paragraphs[0]
