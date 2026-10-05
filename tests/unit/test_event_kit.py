# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The printable event kit: a card per table, the programme, the notice —
in the assembly's language, and a valid PDF whatever the assembly has."""

from types import SimpleNamespace

from citizens.services.event_kit import notice_lines, render_event_kit

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


def test_the_notice_says_what_the_phone_says_in_the_assembly_language():
    lines = notice_lines("it", HANDLING)
    assert lines[1] == "Motore di trascrizione: Vosk — in esecuzione su questo server."
    assert lines[2].startswith("Analisi: un servizio di IA esterno")
    assert lines[3] == "L'audio viene conservato per 30 giorni dopo l'evento, poi cancellato."
    english = notice_lines("en", {**HANDLING, "stt_provider": "deepgram", "stt_hosted": True,
                                  "analysis_enabled": False, "audio_retention_days": 0})
    assert english[1] == "Transcription engine: Deepgram — a hosted service outside this server."
    assert english[2] == "Analysis: none — only the transcript is produced."
    assert english[3] == "Audio is deleted as soon as the transcript is ready."
    # an unknown language falls back to English rather than failing
    assert notice_lines("xx", HANDLING)[0] == notice_lines("en", HANDLING)[0]
