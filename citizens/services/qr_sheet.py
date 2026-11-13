# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The printable QR sheet: four table codes per A4 page, with cut lines.

Built server-side rather than with window.print(). Browser printing silently
dropped every page after the first, and the layout also has to survive
Nextcloud's global CSS, which we do not control.

fpdf2 gotcha worth knowing before touching this: the `qr_svg` stored on an
invite CANNOT be handed to fpdf2. segno serialises it with `svgns=False`, and
fpdf2's SVGObject rejects a root element with no namespace. The QR is
regenerated here as PNG from the join URL instead, which fpdf2 embeds
natively — so this module only ever needs (table_number, url) and never
touches token material beyond what is already in the URL.
"""

import io
from pathlib import Path

import segno
from fpdf import FPDF

from citizens.services.report_pdf import _FONT_DIR, MUTED

# 2 x 2 on A4, so 20 tables print as five sheets
COLUMNS = 2
ROWS = 2
PER_PAGE = COLUMNS * ROWS
QR_MM = 62  # readable from a phone held at arm's length


class _SheetPDF(FPDF):
    def __init__(self, footer_text: str) -> None:
        super().__init__(format="A4")
        self.footer_text = footer_text
        self.set_margins(10, 10, 10)
        self.set_auto_page_break(auto=False)  # the grid is placed by hand
        self.family = "helvetica"
        regular = _FONT_DIR / "DejaVuSans.ttf"
        bold = _FONT_DIR / "DejaVuSans-Bold.ttf"
        if regular.is_file() and bold.is_file():
            self.add_font("DejaVu", "", str(regular))
            self.add_font("DejaVu", "B", str(bold))
            self.family = "DejaVu"

    def footer(self) -> None:
        self.set_y(-8)
        self.set_font(self.family, "", 7)
        self.set_text_color(*MUTED)
        self.cell(0, 4, self.footer_text, new_x="RIGHT", new_y="TOP")
        self.set_y(-8)
        self.cell(0, 4, f"Sheet {self.page_no()}", align="R", new_x="LMARGIN", new_y="NEXT")


def _qr_png(url: str) -> io.BytesIO:
    """QR as PNG. Not the stored SVG — see the module docstring."""
    buffer = io.BytesIO()
    # error correction M survives a fold or a coffee ring on a printed sheet
    segno.make(url, error="m").save(buffer, kind="png", scale=10, border=1)
    buffer.seek(0)
    return buffer


def _cut_lines(pdf: _SheetPDF, cell_w: float, cell_h: float) -> None:
    pdf.set_draw_color(200, 203, 208)
    pdf.set_line_width(0.2)
    pdf.set_dash_pattern(dash=1.5, gap=1.5)
    for column in range(1, COLUMNS):
        x = pdf.l_margin + cell_w * column
        pdf.line(x, pdf.t_margin, x, pdf.t_margin + cell_h * ROWS)
    for row in range(1, ROWS):
        y = pdf.t_margin + cell_h * row
        pdf.line(pdf.l_margin, y, pdf.l_margin + cell_w * COLUMNS, y)
    pdf.set_dash_pattern()


def _cell(pdf: _SheetPDF, x: float, y: float, w: float, h: float,
          table_number: int, url: str, heading: str) -> None:
    pdf.set_xy(x, y + 6)
    pdf.set_font(pdf.family, "", 8.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(w, 4, heading[:60], align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_xy(x, y + 11)
    pdf.set_font(pdf.family, "B", 22)
    pdf.set_text_color(20, 22, 26)
    pdf.cell(w, 10, f"TABLE {table_number}", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.image(_qr_png(url), x=x + (w - QR_MM) / 2, y=y + 23, w=QR_MM, h=QR_MM)

    pdf.set_xy(x, y + 23 + QR_MM + 3)
    pdf.set_font(pdf.family, "", 9)
    pdf.set_text_color(20, 22, 26)
    pdf.cell(w, 4.5, "Scan with this table's recording phone", align="C",
             new_x="LMARGIN", new_y="NEXT")

    # the link in full, for a phone that cannot scan
    pdf.set_xy(x + 4, y + 23 + QR_MM + 8)
    pdf.set_font(pdf.family, "", 6)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(w - 8, 2.8, url, align="C", new_x="LMARGIN", new_y="NEXT")


def _poll_cell(pdf: _SheetPDF, x: float, y: float, w: float, h: float,
               url: str, heading: str) -> None:
    """The Polis voting link, for the wall or the tables: scanned with the
    participants' own phones, not the recording phone."""
    pdf.set_xy(x, y + 6)
    pdf.set_font(pdf.family, "", 8.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(w, 4, heading[:60], align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_xy(x, y + 11)
    pdf.set_font(pdf.family, "B", 22)
    pdf.set_text_color(20, 22, 26)
    pdf.cell(w, 10, "VOTE", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.image(_qr_png(url), x=x + (w - QR_MM) / 2, y=y + 23, w=QR_MM, h=QR_MM)

    pdf.set_xy(x, y + 23 + QR_MM + 3)
    pdf.set_font(pdf.family, "", 9)
    pdf.set_text_color(20, 22, 26)
    pdf.cell(w, 4.5, "Scan with your own phone to vote on the statements", align="C",
             new_x="LMARGIN", new_y="NEXT")

    pdf.set_xy(x + 4, y + 23 + QR_MM + 8)
    pdf.set_font(pdf.family, "", 6)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(w - 8, 2.8, url, align="C", new_x="LMARGIN", new_y="NEXT")


def render_qr_sheet(
    assembly_name: str,
    cards: list,
    logo_path: Path | None = None,
    organization_name: str = "",
    poll_url: str | None = None,
) -> bytes:
    """`cards` are InviteGenerated (table_number + url), in table order.
    `poll_url`, when the Polis poll is published, adds one VOTE card per
    page of tables, so every table sheet carries the voting code."""
    heading = " · ".join(part for part in (organization_name, assembly_name) if part)
    pdf = _SheetPDF(footer_text=heading or assembly_name)
    cell_w = (pdf.w - pdf.l_margin - pdf.r_margin) / COLUMNS
    cell_h = (pdf.h - pdf.t_margin - pdf.b_margin - 6) / ROWS

    ordered = sorted(cards, key=lambda card: card.table_number)
    for index, card in enumerate(ordered):
        if index % PER_PAGE == 0:
            pdf.add_page()
            _cut_lines(pdf, cell_w, cell_h)
            if logo_path is not None and logo_path.is_file():
                try:
                    pdf.image(str(logo_path), x=pdf.l_margin, y=3, h=6,
                              keep_aspect_ratio=True)
                except Exception:  # a bad logo must not cost the sheet
                    pass
        slot = index % PER_PAGE
        x = pdf.l_margin + cell_w * (slot % COLUMNS)
        y = pdf.t_margin + cell_h * (slot // COLUMNS)
        _cell(pdf, x, y, cell_w, cell_h, card.table_number, card.url, heading)

    if not ordered and not poll_url:  # an assembly with no invites still returns a valid PDF
        pdf.add_page()
        pdf.set_font(pdf.family, "", 11)
        pdf.cell(0, 10, "No table codes have been generated yet.",
                 new_x="LMARGIN", new_y="NEXT")
    if poll_url:
        # its own page, so the vote cards can be cut and handed out as well
        pdf.add_page()
        _cut_lines(pdf, cell_w, cell_h)
        for slot in range(PER_PAGE):
            x = pdf.l_margin + cell_w * (slot % COLUMNS)
            y = pdf.t_margin + cell_h * (slot // COLUMNS)
            _poll_cell(pdf, x, y, cell_w, cell_h, poll_url, heading)
    return bytes(pdf.output())
