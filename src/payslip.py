"""ADP/Gusto-style payslips (PDF) for ShiftSnap workers.

One PDF per worker per pay period:
  - Company + employee header, pay period & pay date
  - Earnings table: Regular (up to 8h/day) at base rate,
    Overtime (extra hours) at 1.5x — standard US practice
  - Year-to-date hours and gross pay
  - Gross pay only: taxes/deductions are handled by the employer's
    payroll provider, so the slip is labeled accordingly (honest,
    like a real earnings statement's gross section).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .store import fmt_duration, net_minutes
from .timesheet import OUT_DIR, load_profile

NAVY = colors.HexColor("#0b1f3a")
TEAL = colors.HexColor("#0e7c6b")
LIGHT = colors.HexColor("#f1f5f9")
BORDER = colors.HexColor("#dbe3f0")
MUTED = colors.HexColor("#64748b")

TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20,
                       textColor=NAVY, leading=24)
SUB = ParagraphStyle("sub", fontName="Helvetica", fontSize=9,
                     textColor=MUTED, leading=12)
H = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=11,
                   textColor=NAVY, leading=14)
CELL = ParagraphStyle("cell", fontName="Helvetica", fontSize=9.5, leading=13)
CELL_B = ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=9.5,
                        leading=13)
CELL_R = ParagraphStyle("cellr", parent=CELL, alignment=2)   # right
CELL_BR = ParagraphStyle("cellbr", parent=CELL_B, alignment=2)
NOTE = ParagraphStyle("note", fontName="Helvetica-Oblique", fontSize=8,
                      textColor=MUTED, leading=11)


def _money(v: float) -> str:
    return f"${v:,.2f}"


def _shifts(store, worker_id, start, end):
    try:
        return store.list_shifts(start, end, employee_id=worker_id)
    except TypeError:  # JSON demo store has no employee scoping
        return store.list_shifts(start, end)


def _payslip_data(store, worker_id, start: str, end: str,
                  hourly_rate: float) -> dict:
    shifts = _shifts(store, worker_id, start, end)
    reg_min = ot_min = 0
    for day_shifts in shifts.values():
        for s in day_shifts:
            if not s.get("time_out"):
                continue
            mins = net_minutes(s)
            reg_min += min(mins, 8 * 60)
            ot_min += max(mins - 8 * 60, 0)
    reg_pay = round(reg_min / 60 * hourly_rate, 2)
    ot_pay = round(ot_min / 60 * hourly_rate * 1.5, 2)

    year = start[:4]
    ytd_shifts = _shifts(store, worker_id, f"{year}-01-01", end)
    ytd_min = ytd_ot_min = 0
    for ds in ytd_shifts.values():
        for s in ds:
            if not s.get("time_out"):
                continue
            mins = net_minutes(s)
            ytd_min += mins
            ytd_ot_min += max(mins - 8 * 60, 0)
    ytd_gross = round((ytd_min - ytd_ot_min) / 60 * hourly_rate
                      + ytd_ot_min / 60 * hourly_rate * 1.5, 2)
    return {
        "reg_min": reg_min, "ot_min": ot_min,
        "reg_pay": reg_pay, "ot_pay": ot_pay,
        "gross": round(reg_pay + ot_pay, 2),
        "ytd_min": ytd_min, "ytd_gross": ytd_gross,
        "days": len(shifts),
    }


def generate_payslip(start: str, end: str, store, worker_id: str,
                     worker_name: str, hourly_rate: float,
                     pay_date: str | None = None) -> str:
    """Build the payslip PDF. Returns the file path."""
    profile = load_profile()
    company = profile.get("company", profile.get("customer", "ShiftSnap"))
    d = _payslip_data(store, worker_id, start, end, hourly_rate or 0.0)
    pay_date = pay_date or end

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"Payslip_{worker_name.replace(' ', '_')}_{start}_to_{end}.pdf"

    doc = SimpleDocTemplate(str(path), pagesize=LETTER,
                            leftMargin=.75 * inch, rightMargin=.75 * inch,
                            topMargin=.6 * inch, bottomMargin=.6 * inch)
    W = doc.width
    els = []

    # Header
    els.append(Paragraph(company.upper(), TITLE))
    els.append(Paragraph("EARNINGS STATEMENT", SUB))
    els.append(Spacer(1, 14))

    hdr = [
        [Paragraph("<b>Employee</b>", CELL), Paragraph(worker_name, CELL),
         Paragraph("<b>Pay period</b>", CELL),
         Paragraph(f"{start} to {end}", CELL)],
        [Paragraph("<b>Employee ID</b>", CELL),
         Paragraph(str(worker_id)[:8], CELL),
         Paragraph("<b>Pay date</b>", CELL), Paragraph(pay_date, CELL)],
        [Paragraph("<b>Classification</b>", CELL),
         Paragraph(profile.get("classification", ""), CELL),
         Paragraph("<b>Project</b>", CELL),
         Paragraph(str(profile.get("project_code", "")), CELL)],
    ]
    t = Table(hdr, colWidths=[1.25 * inch, 2.4 * inch, 1.25 * inch, 2.1 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT),
        ("BACKGROUND", (2, 0), (2, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), .75, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), .5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    els.append(t)
    els.append(Spacer(1, 18))

    # Earnings
    els.append(Paragraph("EARNINGS", H))
    els.append(Spacer(1, 6))
    earn = [
        [Paragraph("<b>Description</b>", CELL_B),
         Paragraph("<b>Hours</b>", CELL_BR),
         Paragraph("<b>Rate</b>", CELL_BR),
         Paragraph("<b>Current</b>", CELL_BR),
         Paragraph("<b>YTD</b>", CELL_BR)],
        [Paragraph("Regular", CELL),
         Paragraph(fmt_duration(d["reg_min"]), CELL_R),
         Paragraph(_money(hourly_rate or 0), CELL_R),
         Paragraph(_money(d["reg_pay"]), CELL_R),
         Paragraph(fmt_duration(d["ytd_min"]), CELL_R)],
        [Paragraph("Overtime (1.5×)", CELL),
         Paragraph(fmt_duration(d["ot_min"]), CELL_R),
         Paragraph(_money((hourly_rate or 0) * 1.5), CELL_R),
         Paragraph(_money(d["ot_pay"]), CELL_R),
         Paragraph("—", CELL_R)],
        [Paragraph("<b>GROSS PAY</b>", CELL_B),
         Paragraph(f"<b>{fmt_duration(d['reg_min'] + d['ot_min'])}</b>",
                   CELL_BR),
         Paragraph("", CELL), Paragraph(f"<b>{_money(d['gross'])}</b>",
                                         CELL_BR),
         Paragraph(f"<b>{_money(d['ytd_gross'])}</b>", CELL_BR)],
    ]
    et = Table(earn, colWidths=[2.2 * inch, 1.1 * inch, 1.1 * inch,
                               1.3 * inch, 1.3 * inch])
    et.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, -1), (-1, -1), LIGHT),
        ("LINEABOVE", (0, -1), (-1, -1), 1.25, NAVY),
        ("BOX", (0, 0), (-1, -1), .75, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), .5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    els.append(et)
    els.append(Spacer(1, 10))
    els.append(Paragraph(
        f"Days worked this period: <b>{d['days']}</b> &nbsp;·&nbsp; "
        "Taxes and deductions are handled by your employer's payroll "
        "provider and are not shown here.", NOTE))
    els.append(Spacer(1, 20))

    # Summary strip
    summ = [[
        Paragraph(f"<b>{_money(d['gross'])}</b><br/><font size=8 "
                  "color='#64748b'>GROSS PAY</font>", CELL),
        Paragraph(f"<b>{fmt_duration(d['reg_min'] + d['ot_min'])}</b><br/>"
                  "<font size=8 color='#64748b'>TOTAL HOURS</font>", CELL),
        Paragraph(f"<b>{_money(hourly_rate or 0)}/h</b><br/><font size=8 "
                  "color='#64748b'>BASE RATE</font>", CELL),
    ]]
    st = Table(summ, colWidths=[W / 3] * 3)
    st.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0e7c6b")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("ROUNDEDCORNERS", [8, 8, 8, 8]),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
    ]))
    els.append(st)
    els.append(Spacer(1, 24))
    els.append(Paragraph(
        "Generated by ShiftSnap. This statement reflects recorded shift "
        "punches and the worker's current pay rate.", NOTE))

    doc.build(els)
    return str(path)
