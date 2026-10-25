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
from citizens.services.consent_notice import render_notice
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
        "kit": "Kit dell'evento",
    },
}

def _t(language: str | None, key: str, **fmt) -> str:
    strings = _TEXT.get(normalize_language(language), _TEXT["en"])
    template = strings.get(key) or _TEXT["en"][key]
    return template.format(**fmt) if fmt else template


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
    organization: dict | None = None,
    auto_purge: bool = True,
) -> bytes:
    """`cards` are InviteGenerated (table_number + url); `rounds` dicts with
    position, title, question, objective, duration_minutes; `handling` is
    data_handling_summary() and `organization` organization_data(), both read
    by the caller, never here. The notice page is the consent notice itself
    (services/consent_notice.py), so paper and phone say the same thing."""
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
    notice = render_notice(
        language, handling, organization_name=organization_name,
        organization=organization, auto_purge=auto_purge,
    )
    for line in notice.paragraphs:
        pdf.multi_cell(0, 6.5, line, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    pdf.set_auto_page_break(auto=False)
    return bytes(pdf.output())
