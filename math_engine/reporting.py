"""
math_engine.reporting
---------------------
One-page PDF reports via ReportLab - shared by the REST API
(GET /api/wells/{id}/report.pdf) and the Streamlit dashboard's
download button, so both outputs stay identical.

Structure is deliberately simple: a list of (heading, [lines]) sections
rendered top-down with automatic page breaks.

Partnerships hook (business plan 4.3): set AEROLIFT_QUOTE_URL to append
a "Request Quote" call-to-action in every report footer.
"""

import io
import os

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

QUOTE_URL = os.environ.get("AEROLIFT_QUOTE_URL", "")

MARGIN = 0.75 * inch


def build_report(title: str, subtitle: str,
                 sections, footer_note: str = None) -> bytes:
    """
    :param sections: iterable of (heading:str, lines:list[str])
    :returns: PDF file content as bytes.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter
    y = height - MARGIN

    def _newpage():
        nonlocal y
        c.showPage()
        y = height - MARGIN

    c.setFont("Helvetica-Bold", 16)
    c.drawString(MARGIN, y, title)
    y -= 0.28 * inch
    if subtitle:
        c.setFont("Helvetica", 9)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        c.drawString(MARGIN, y, subtitle[:140])
        c.setFillColorRGB(0, 0, 0)
        y -= 0.32 * inch

    for heading, lines in sections:
        if not lines:
            continue
        if y < 1.8 * inch:
            _newpage()
        c.setFont("Helvetica-Bold", 11.5)
        c.drawString(MARGIN, y, str(heading))
        y -= 0.22 * inch
        c.setFont("Helvetica", 9)
        for line in lines:
            if y < 1.15 * inch:
                _newpage()
                c.setFont("Helvetica", 9)
            c.drawString(MARGIN + 0.12 * inch, y, str(line)[:115])
            y -= 0.165 * inch
        y -= 0.10 * inch

    # Footer: quote CTA + provenance
    footer_y = 0.62 * inch
    c.setFillColorRGB(0.90, 0.93, 0.98)
    c.rect(0, 0, width, 0.85 * inch, stroke=0, fill=1)
    c.setFillColorRGB(0.10, 0.25, 0.55)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(MARGIN, footer_y + 0.14 * inch,
                 "AeroLift Analytics - Lee & Wattenbarger physics "
                 "(DAK/Sutton/LGE, Beggs & Brill, Turner/Coleman)")
    c.setFont("Helvetica", 8.5)
    note = footer_note or ""
    if QUOTE_URL:
        c.drawString(MARGIN, footer_y - 0.02 * inch,
                     "Request Quote / Solicitar intervencion: {}"
                     .format(QUOTE_URL))
        if note:
            c.drawRightString(width - MARGIN, footer_y - 0.02 * inch,
                              note[:70])
    elif note:
        c.drawString(MARGIN, footer_y - 0.02 * inch, note[:130])
    c.showPage()
    c.save()
    return buf.getvalue()
