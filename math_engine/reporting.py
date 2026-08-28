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


def portfolio_report_sections(summary: dict, rows: list,
                              budget: dict = None) -> list:
    """Sections for the executive portfolio PDF.

    :param summary: portfolio_summary() dict.
    :param rows: ranked reports (only best-option flats are used).
    :param budget: optimize_budget() dict or None.
    Names are padded to a fixed width so the one-page canvas renders
    readable fixed-with columns out of the box.
    """
    def _usd(x):
        if x is None:
            return "-"
        return "{:,.0f}".format(float(x))

    def _num(x, d=0):
        if x is None:
            return "-"
        return "{:,.{}f}".format(float(x), d)

    sections = []
    sections.append((
        "Resumen de campo",
        [
            "Pozos: {}   En riesgo: {}   Accionables: {}".format(
                summary["wells_total"], summary["wells_at_risk"],
                summary["wells_actionable"]),
            "Gas en riesgo: {:.0f} Mscf/D   Gas recuperable: {:.0f} "
            "Mscf/D".format(summary["gas_at_risk_mscfd"],
                            summary["gas_actionable_mscfd"]),
            "NPV positivo: $ {}   Costo: $ {}   DeltaGas: {} MMscf".
            format(_usd(summary["positive_npv_usd"]),
                   _usd(summary["positive_cost_usd"]),
                   _num(summary["positive_incremental_gas_mmscf"], 1)),
            "ROI medio: {} %   Payback medio: {} meses".format(
                _num(summary["positive_roi_mean_pct"]),
                _num(summary["positive_payback_mean_months"])),
        ]))

    lines = []
    positives = 0
    for r in rows:
        flat = r["best_option"] or {}
        name = str(flat.get("tag") or r.get("tag") or "-")[:15].ljust(15)
        action = str(flat.get("intervention") or "sin-opcion")[:14].ljust(14)
        npv = _usd(flat.get("npv_usd"))
        roi = _num(flat.get("roi_pct"))
        pay = _num(flat.get("payback_months"))
        gas = _num(flat.get("incremental_gas_mmscf"), 1)
        cost = _usd(flat.get("cost_usd"))
        lines.append("{} {} NPV $ {} | ROI {} % | payback {}m | "
                     "dGas {} MMscf | costo $ {}".format(
                         name, action, npv, roi, pay, gas, cost))
        if flat.get("npv_usd"):
            positives += 1
    sections.append(("Ranking por pozo ({} con NPV)".format(positives),
                     lines))

    if budget:
        selections = []
        for o in budget["chosen"]:
            name = str(o.get("tag") or o.get("well_id") or "-")[:15].ljust(15)
            selections.append(
                "{} {}  NPV $ {}  costo $ {}".format(
                    name, str(o["intervention"])[:14].ljust(14),
                    _usd(o["npv_usd"]), _usd(o["cost_usd"])))
        sections.append((
            "Paquete optimo (presupuesto $ {})".format(
                _usd(budget["budget_usd"])),
            selections + [
                "Total: $ {} de $ {} ({} % uso) | NPV $ {} | "
                "{} pozos".format(
                    _usd(budget["total_cost_usd"]),
                    _usd(budget["budget_usd"]),
                    _num(budget["utilization_pct"], 1),
                    _usd(budget["total_npv_usd"]),
                    budget["wells_selected"]),
            ]))
    return sections
