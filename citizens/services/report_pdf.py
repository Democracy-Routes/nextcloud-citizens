# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""PDF rendering of the assembly report (fpdf2).

Institutional layout: compact branded header (logo + organization name),
executive summary of every round, accent section banners, findings grouped by
type in deliberation-report order with colored badges, evidence quotes with a
drawn left bar, running footer with page numbers.

DejaVu Sans (fonts-dejavu-core in the image) provides Unicode coverage; when
the font is unavailable (bare dev host) the renderer falls back to Helvetica.

fpdf2 gotcha encoded here once: every multi_cell/cell passes explicit
new_x/new_y — the default parks the cursor at the right margin, zeroing the
width of the next block.
"""

from datetime import UTC, datetime
from pathlib import Path

from fpdf import FPDF

from citizens.services.report import TYPE_LABELS_SINGULAR, group_findings_by_type, round_heading

_FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")

INK = (34, 34, 34)
MUTED = (107, 107, 107)
ACCENT = (0, 103, 158)  # NC blue
LIGHT = (238, 240, 243)
AMBER = (163, 106, 0)  # points of divergence

BADGE_COLORS = {
    "proposal": ACCENT,
    "agreement": (45, 123, 65),
    "disagreement": AMBER,
    "concern": (192, 80, 0),
    "question": (85, 85, 95),
    "minority_position": (106, 79, 163),
    "new_idea": (0, 121, 107),
}


class _ReportPDF(FPDF):
    def __init__(self, footer_text: str) -> None:
        super().__init__(format="A4")
        self.footer_text = footer_text
        self.set_margins(18, 16, 18)
        self.set_auto_page_break(auto=True, margin=20)
        self.family = "helvetica"
        regular = _FONT_DIR / "DejaVuSans.ttf"
        bold = _FONT_DIR / "DejaVuSans-Bold.ttf"
        if regular.is_file() and bold.is_file():
            self.add_font("DejaVu", "", str(regular))
            self.add_font("DejaVu", "B", str(bold))
            self.family = "DejaVu"

    def footer(self) -> None:
        self.set_y(-14)
        self.set_draw_color(210, 213, 218)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_y(-11)
        self.set_font(self.family, "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(0, 5, self.footer_text, new_x="RIGHT", new_y="TOP")
        self.set_y(-11)
        self.cell(0, 5, str(self.page_no()), align="R", new_x="LMARGIN", new_y="NEXT")

    # helpers -----------------------------------------------------------

    def text_block(self, text: str, size: float = 10.5, style: str = "",
                   color: tuple = INK, height: float = 5.2, indent: float = 0) -> None:
        self.set_font(self.family, style, size)
        self.set_text_color(*color)
        if indent:
            self.set_x(self.l_margin + indent)
        self.multi_cell(
            self.w - self.l_margin - self.r_margin - indent, height, text,
            new_x="LMARGIN", new_y="NEXT",
        )

    def block_height(self, text: str, size: float = 10.5, style: str = "",
                     height: float = 5.2, indent: float = 0) -> float:
        """How tall text_block() would be, without drawing anything.

        fpdf2's dry run reports the height and leaves the cursor alone. Used
        instead of unbreakable()/offset_rendering(), which work by duplicating
        the output buffer — needless here, and this runs on a small host.
        """
        self.set_font(self.family, style, size)
        return float(
            self.multi_cell(
                self.w - self.l_margin - self.r_margin - indent, height, text,
                dry_run=True, output="HEIGHT", new_x="LMARGIN", new_y="NEXT",
            )
        )

    def keep_together(self, needed: float) -> bool:
        """Start a new page if `needed` mm will not fit on this one.

        Returns whether it did, so a caller that draws its own decoration knows
        the block is now on a single page. A block taller than a whole page
        cannot be kept together at all — say so rather than looping.
        """
        if needed > self.eph:
            return False
        if self.will_page_break(needed):
            self.add_page()
        return True

    def eyebrow(self, text: str, color: tuple = MUTED) -> None:
        self.set_font(self.family, "B", 8)
        self.set_text_color(*color)
        self.cell(0, 5, text.upper(), new_x="LMARGIN", new_y="NEXT")

    def section_banner(self, title: str) -> None:
        # a banner alone at the foot of a page is just a heading with nothing
        # under it: reserve the banner plus a couple of lines of what follows
        if self.will_page_break(10 + 3 + 16):
            self.add_page()
        self.ln(5)
        self.set_fill_color(*ACCENT)
        self.set_font(self.family, "B", 13)
        self.set_text_color(255, 255, 255)
        self.cell(0, 10, f"  {title}", fill=True, new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def group_heading(self, title: str, accent: tuple = ACCENT) -> None:
        self.ln(2)
        self.set_font(self.family, "B", 11)
        self.set_text_color(*accent)
        self.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*accent)
        self.set_line_width(0.4)
        self.line(self.l_margin, self.get_y(), self.l_margin + 26, self.get_y())
        self.ln(2.5)

    def badge(self, text: str, color: tuple) -> None:
        self.set_font(self.family, "B", 7)
        width = self.get_string_width(text.upper()) + 4
        self.set_fill_color(*color)
        self.set_text_color(255, 255, 255)
        self.cell(width, 4.6, text.upper(), fill=True, align="C", new_x="RIGHT", new_y="TOP")
        self.cell(2, 4.6, "", new_x="RIGHT", new_y="TOP")


def _finding(pdf: _ReportPDF, finding: dict, cross: bool) -> None:
    # enough for the badge, the title and the first line of the summary; the
    # evidence block below measures itself
    if pdf.will_page_break(6 + 5.4 + 5):
        pdf.add_page()
    label = TYPE_LABELS_SINGULAR.get(finding["type"], finding["type"])
    color = BADGE_COLORS.get(finding["type"], MUTED)
    pdf.badge(label, color)
    if finding["is_draft"]:
        pdf.badge("draft — not reviewed", (150, 150, 150))
    pdf.ln(6)
    pdf.text_block(finding["title"], size=11, style="B", height=5.4)
    if cross and finding["mentioned_table_count"]:
        pdf.text_block(
            f"Mentioned at {finding['mentioned_table_count']} table(s)",
            size=8.5, style="B", color=color, height=4.4,
        )
    pdf.text_block(finding["summary"], height=5)
    # already chosen and capped by report._quotes(); do not re-truncate here
    quotes = finding["evidence"]
    if not quotes and finding.get("evidence_removed"):
        pdf.text_block("Evidence removed with the transcript.", size=9, color=MUTED, height=4.6,
                       indent=5)
    if quotes:
        lines = [
            (f"Table {evidence['table_number']} · " if evidence.get("table_number") else "")
            + f"[{evidence['timestamp']}] {evidence['speaker'] or 'Speaker'}: “{evidence['text']}”"
            for evidence in quotes
        ]
        # The accent bar is one line() from where the quotes began to where they
        # ended, and both are page-agnostic. When the block straddled a page
        # break, get_y() had reset to the top of the NEW page, so the bar was
        # drawn there running almost its full height — and the page that
        # actually held the first quotes got no bar at all. Measured in a real
        # report: 627, 649 and 663pt bars on an 842pt page.
        #
        # Keeping the block on one page fixes the bar and reads better; a
        # citation split across a page break is hard to follow either way.
        heights = [pdf.block_height(line, size=9, height=4.6, indent=5) for line in lines]
        whole = pdf.keep_together(sum(heights) + 1)
        pdf.ln(1)
        pdf.set_draw_color(*color)
        pdf.set_line_width(0.7)
        y_start = pdf.get_y()
        for line, line_height in zip(lines, heights, strict=True):
            if not whole and pdf.will_page_break(line_height):
                # Taller than a page even after truncation to five quotes: close
                # the bar off here and start it again after the break, so every
                # page carries the segment that belongs to it.
                pdf.line(pdf.l_margin + 1.5, y_start, pdf.l_margin + 1.5, pdf.get_y() - 0.5)
                pdf.add_page()
                y_start = pdf.get_y()
            pdf.text_block(line, size=9, color=MUTED, height=4.6, indent=5)
        pdf.line(pdf.l_margin + 1.5, y_start, pdf.l_margin + 1.5, pdf.get_y() - 0.5)
    pdf.ln(3)


def render_pdf(report: dict, logo_path: Path | None = None,
               organization_name: str = "") -> bytes:
    assembly = report["assembly"]
    footer_text = " · ".join(part for part in (organization_name, assembly["name"]) if part)
    pdf = _ReportPDF(footer_text or assembly["name"])
    pdf.add_page()

    # ---- compact branded header ----
    header_top = pdf.get_y()
    right_w = 42.0
    if logo_path is not None and logo_path.is_file():
        pdf.image(str(logo_path), x=pdf.w - pdf.r_margin - right_w, y=header_top,
                  h=14, w=right_w, keep_aspect_ratio=True)
    if organization_name:
        pdf.set_xy(pdf.w - pdf.r_margin - right_w, header_top + (16 if logo_path else 0))
        pdf.set_font(pdf.family, "B", 8.5)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(right_w, 4, organization_name, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(pdf.l_margin, header_top)

    title_w = pdf.w - pdf.l_margin - pdf.r_margin - right_w - 6
    pdf.set_font(pdf.family, "B", 20)
    pdf.set_text_color(*INK)
    pdf.multi_cell(title_w, 9, assembly["name"], new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(pdf.family, "B", 11)
    pdf.set_text_color(*ACCENT)
    pdf.cell(title_w, 7, "Assembly Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.8)
    pdf.line(pdf.l_margin, pdf.get_y() + 1.5, pdf.l_margin + 42, pdf.get_y() + 1.5)
    pdf.ln(5)

    # the document states plainly whether it is the final artifact
    progress = report.get("progress") or {}
    if report.get("is_final"):
        closed = (report.get("closed_at") or "")[:10]
        pdf.text_block(f"FINAL REPORT · closed {closed}", size=9, style="B", color=ACCENT,
                       height=4.6)
    else:
        pdf.text_block(
            f"INTERIM REPORT · {progress.get('tables_complete', 0)} of "
            f"{progress.get('tables_expected', 0)} tables have completed all rounds",
            size=9, style="B", color=AMBER, height=4.6,
        )
    generated = datetime.now(UTC).strftime("%-d %B %Y")
    # The participant count is a live count of the organizer's roster, and
    # recording a table creates no roster entry — so an assembly that ran
    # perfectly well without one announced "0 participants (expected 50)" on
    # the cover of its final report. Say nothing rather than say zero.
    meta = [generated]
    if assembly["participants"]:
        meta.append(
            f"{assembly['participants']} participants "
            f"(expected {assembly['expected_participants']})"
        )
    meta += [f"{assembly['tables']} tables", assembly["language"].upper()]
    pdf.text_block(" · ".join(meta), size=9.5, color=MUTED)
    if progress.get("tables_expected"):
        pdf.text_block(
            f"{progress.get('tables_contributed', 0)} of "
            f"{progress['tables_expected']} tables contributed to this report",
            size=9, color=MUTED, height=4.4,
        )
    pdf.ln(2)
    if assembly["description"]:
        pdf.text_block(assembly["description"])
        pdf.ln(2)
    pdf.eyebrow("Method")
    pdf.text_block(report["method"], size=9.5, color=MUTED, height=4.8)

    # ---- executive summary (aggregated round summaries) ----
    summaries = [r for r in report["rounds"] if r["summary"]]
    if summaries:
        pdf.section_banner("Executive summary")
        pdf.text_block(
            "AI-generated overview of each round across all tables; details and "
            "human-reviewed findings follow.",
            size=8.5, color=MUTED, height=4.4,
        )
        pdf.ln(1.5)
        for round_ in summaries:
            pdf.text_block(
                round_heading(round_["position"], round_["title"]),
                size=10.5, style="B", height=5,
            )
            pdf.text_block(round_["summary"], height=5)
            pdf.ln(1.5)

    # ---- rounds ----
    for round_ in report["rounds"]:
        pdf.section_banner(round_heading(round_["position"], round_["title"]))
        if round_["question"]:
            pdf.text_block(f"“{round_['question']}”", size=11.5, style="B", color=ACCENT)
            pdf.ln(1.5)
        if round_["summary"]:
            pdf.eyebrow("AI summary — all tables")
            pdf.text_block(round_["summary"], height=5)
            pdf.ln(1.5)

        for type_, label, group in group_findings_by_type(round_["cross_table"]):
            pdf.group_heading(label, AMBER if type_ == "disagreement" else ACCENT)
            for finding in group:
                _finding(pdf, finding, cross=True)

        tables_with_content = [
            t for t in round_["tables"] if t["findings"] or t["summary"]
        ]
        if tables_with_content:
            pdf.group_heading("Table detail", MUTED)
            for table in tables_with_content:
                pdf.eyebrow(f"Table {table['table_number']}", ACCENT)
                if table["summary"]:
                    pdf.text_block(table["summary"], size=9.5, color=MUTED, height=4.8)
                    pdf.ln(1)
                for finding in table["findings"]:
                    _finding(pdf, finding, cross=False)
                pdf.ln(1)

        if (
            not round_["summary"]
            and not round_["cross_table"]
            and not tables_with_content
        ):
            pdf.text_block("No findings for this round yet.", color=MUTED)

    # The rule and the note are one thing. Drawn without measuring, the rule
    # landed near the foot of the page and the note overflowed, leaving two
    # orphaned lines on a page of their own. Its length varies run to run —
    # _methodology_note() appends a paragraph for live captions and another for
    # a replaced device — so a fixed margin would not have held either.
    note = report["methodology_note"]
    pdf.ln(5)
    pdf.keep_together(pdf.block_height(note, size=8.5, height=4.4) + 3)
    pdf.set_draw_color(*MUTED)
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(3)
    pdf.text_block(note, size=8.5, color=MUTED, height=4.4)

    return bytes(pdf.output())
