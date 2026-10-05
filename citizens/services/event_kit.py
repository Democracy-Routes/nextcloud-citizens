# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The printable event kit: a table card per table, the programme, the notice.

What an organizer puts on the tables and at the door the morning of the
event, printed the evening before. One A5 card per table (two per A4 sheet,
cut line between): the number large, a band in the table's colour so "the
blue table" means something across the room, the QR that joins a phone to
it, and the join link in full for a phone that cannot scan. Then a page with
the programme — every session with its question, objective and duration —
and a page with the recording notice in the assembly's language, the same
facts the phone shows before recording starts.

Built on the QR sheet's renderer (services/qr_sheet.py) and its fpdf2
caveats: the QR is regenerated as PNG from the join URL, never from the
stored SVG. The kit only ever needs (table_number, url) for a code.
"""

from pathlib import Path

from citizens.domain.tables import color_for
from citizens.services.qr_sheet import QR_MM, _qr_png, _SheetPDF
from citizens.services.report_pdf import INK, MUTED
from citizens.services.report_text import normalize_language

# the palette on paper — the same hues the screens use, printable
TABLE_RGB = {
    "blue": (0, 103, 158),
    "green": (45, 123, 65),
    "orange": (192, 80, 0),
    "purple": (106, 79, 163),
    "red": (198, 40, 40),
    "teal": (0, 121, 107),
}

_TEXT = {
    "en": {
        "table": "TABLE {number}",
        "scan": "Scan with this table's recording phone",
        "programme": "Programme",
        "session": "Session {position}",
        "question": "Question",
        "objective": "Objective",
        "duration": "{minutes} minutes",
        "no_sessions": "No sessions have been planned yet.",
        "notice": "Before we record",
        "notice_intro": (
            "This discussion is recorded with the phone on the table. The recording is "
            "transcribed and analysed to produce the assembly's report. Names are replaced "
            "by pseudonyms before any text leaves the server."
        ),
        "stt_hosted": "Transcription engine: {provider} — a hosted service outside this server.",
        "stt_local": "Transcription engine: {provider} — running on this server.",
        "analysis_hosted": "Analysis: a hosted AI service reads the pseudonymised transcript.",
        "analysis_local": "Analysis: an AI model running on this server reads the transcript.",
        "analysis_off": "Analysis: none — only the transcript is produced.",
        "retention": "Audio is kept for {days} days after the event, then deleted.",
        "retention_none": "Audio is deleted as soon as the transcript is ready.",
        "consent": (
            "Taking part in the recorded discussion is voluntary. Anyone who prefers not to be "
            "recorded can say so to the facilitator before the session starts."
        ),
        "kit": "Event kit",
    },
    "it": {
        "table": "TAVOLO {number}",
        "scan": "Scansiona con il telefono che registra questo tavolo",
        "programme": "Programma",
        "session": "Sessione {position}",
        "question": "Domanda",
        "objective": "Obiettivo",
        "duration": "{minutes} minuti",
        "no_sessions": "Nessuna sessione è ancora stata pianificata.",
        "notice": "Prima di registrare",
        "notice_intro": (
            "Questa discussione viene registrata con il telefono sul tavolo. La registrazione "
            "viene trascritta e analizzata per produrre il rapporto dell'assemblea. I nomi "
            "vengono sostituiti da pseudonimi prima che qualsiasi testo lasci il server."
        ),
        "stt_hosted": "Motore di trascrizione: {provider} — un servizio esterno a questo server.",
        "stt_local": "Motore di trascrizione: {provider} — in esecuzione su questo server.",
        "analysis_hosted": "Analisi: un servizio di IA esterno legge la trascrizione pseudonimizzata.",
        "analysis_local": "Analisi: un modello di IA su questo server legge la trascrizione.",
        "analysis_off": "Analisi: nessuna — viene prodotta solo la trascrizione.",
        "retention": "L'audio viene conservato per {days} giorni dopo l'evento, poi cancellato.",
        "retention_none": "L'audio viene cancellato appena la trascrizione è pronta.",
        "consent": (
            "Partecipare alla discussione registrata è volontario. Chi preferisce non essere "
            "registrato può dirlo a chi facilita prima dell'inizio della sessione."
        ),
        "kit": "Kit dell'evento",
    },
}

_PROVIDER_NAMES = {
    "vosk": "Vosk",
    "whisper": "Whisper",
    "openai": "OpenAI",
    "deepgram": "Deepgram",
    "assemblyai": "AssemblyAI",
    "speechmatics": "Speechmatics",
    "azure": "Azure Speech",
    "google": "Google Speech",
}


def _t(language: str | None, key: str, **fmt) -> str:
    strings = _TEXT.get(normalize_language(language), _TEXT["en"])
    template = strings.get(key) or _TEXT["en"][key]
    return template.format(**fmt) if fmt else template


def notice_lines(language: str | None, handling: dict) -> list[str]:
    """The recording notice as sentences — the facts the phone shows, on paper."""
    provider = handling.get("stt_provider") or ""
    provider_name = _PROVIDER_NAMES.get(provider, provider or "—")
    lines = [_t(language, "notice_intro")]
    lines.append(
        _t(language, "stt_hosted" if handling.get("stt_hosted") else "stt_local", provider=provider_name)
    )
    if not handling.get("analysis_enabled"):
        lines.append(_t(language, "analysis_off"))
    elif handling.get("analysis_hosted"):
        lines.append(_t(language, "analysis_hosted"))
    else:
        lines.append(_t(language, "analysis_local"))
    days = int(handling.get("audio_retention_days") or 0)
    lines.append(_t(language, "retention", days=days) if days > 0 else _t(language, "retention_none"))
    lines.append(_t(language, "consent"))
    return lines


def _card(pdf: _SheetPDF, y: float, h: float, number: int, url: str, language: str | None,
          heading: str) -> None:
    """One A5 landscape card in the top or bottom half of the sheet."""
    x = pdf.l_margin
    w = pdf.w - pdf.l_margin - pdf.r_margin
    band = TABLE_RGB.get(color_for(number), TABLE_RGB["blue"])
    # the colour band down the left edge, wide enough to read across a room
    pdf.set_fill_color(*band)
    pdf.rect(x, y, 14, h, style="F")

    pdf.set_xy(x + 18, y + 8)
    pdf.set_font(pdf.family, "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(w - 18 - QR_MM - 10, 5, heading[:70], new_x="LMARGIN", new_y="NEXT")

    pdf.set_xy(x + 18, y + 16)
    pdf.set_font(pdf.family, "B", 54)
    pdf.set_text_color(*band)
    pdf.cell(w - 18 - QR_MM - 10, 24, _t(language, "table", number=number), new_x="LMARGIN", new_y="NEXT")

    pdf.set_xy(x + 18, y + 44)
    pdf.set_font(pdf.family, "", 11)
    pdf.set_text_color(*INK)
    pdf.multi_cell(w - 18 - QR_MM - 10, 6, _t(language, "scan"), new_x="LMARGIN", new_y="NEXT")

    pdf.image(_qr_png(url), x=x + w - QR_MM - 6, y=y + (h - QR_MM) / 2 - 4, w=QR_MM, h=QR_MM)

    # the link in full, for a phone that cannot scan
    pdf.set_xy(x + 18, y + h - 12)
    pdf.set_font(pdf.family, "", 6.5)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(w - 24, 3, url, new_x="LMARGIN", new_y="NEXT")


def _heading(pdf: _SheetPDF, title: str) -> None:
    pdf.set_font(pdf.family, "B", 20)
    pdf.set_text_color(*INK)
    pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


def render_event_kit(
    assembly_name: str,
    language: str | None,
    cards: list,
    rounds: list[dict],
    handling: dict,
    logo_path: Path | None = None,
    organization_name: str = "",
) -> bytes:
    """`cards` are InviteGenerated (table_number + url); `rounds` dicts with
    position, title, question, objective, duration_minutes; `handling` is
    data_handling_summary() read by the caller, never here."""
    heading = " · ".join(part for part in (organization_name, assembly_name) if part)
    pdf = _SheetPDF(footer_text=f"{heading or assembly_name} — {_t(language, 'kit')}")
    half = (pdf.h - pdf.t_margin - pdf.b_margin - 6) / 2

    ordered = sorted(cards, key=lambda card: card.table_number)
    for index, card in enumerate(ordered):
        if index % 2 == 0:
            pdf.add_page()
            if logo_path is not None and logo_path.is_file():
                try:
                    pdf.image(str(logo_path), x=pdf.l_margin, y=3, h=6, keep_aspect_ratio=True)
                except Exception:  # a bad logo must not cost the kit
                    pass
            # the cut line between the two cards
            pdf.set_draw_color(200, 203, 208)
            pdf.set_line_width(0.2)
            pdf.set_dash_pattern(dash=1.5, gap=1.5)
            pdf.line(pdf.l_margin, pdf.t_margin + half, pdf.w - pdf.r_margin, pdf.t_margin + half)
            pdf.set_dash_pattern()
        y = pdf.t_margin + half * (index % 2)
        _card(pdf, y + 2, half - 4, card.table_number, card.url, language, heading)

    # the programme
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=12)
    _heading(pdf, _t(language, "programme"))
    if not rounds:
        pdf.set_font(pdf.family, "", 11)
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 8, _t(language, "no_sessions"), new_x="LMARGIN", new_y="NEXT")
    for round_ in sorted(rounds, key=lambda r: r.get("position", 0)):
        pdf.set_font(pdf.family, "B", 13)
        pdf.set_text_color(*INK)
        title = round_.get("title") or ""
        label = _t(language, "session", position=round_.get("position", 0))
        pdf.cell(0, 8, f"{label}{' — ' + title if title else ''}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(pdf.family, "", 9.5)
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 5, _t(language, "duration", minutes=round_.get("duration_minutes", 0)),
                 new_x="LMARGIN", new_y="NEXT")
        for key in ("question", "objective"):
            value = (round_.get(key) or "").strip()
            if not value:
                continue
            pdf.set_font(pdf.family, "B", 9.5)
            pdf.set_text_color(*INK)
            pdf.cell(0, 5, _t(language, key), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(pdf.family, "", 10.5)
            pdf.multi_cell(0, 5.5, value, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    # the notice
    pdf.add_page()
    _heading(pdf, _t(language, "notice"))
    pdf.set_font(pdf.family, "", 11)
    pdf.set_text_color(*INK)
    for line in notice_lines(language, handling):
        pdf.multi_cell(0, 6.5, line, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    pdf.set_auto_page_break(auto=False)
    return bytes(pdf.output())
