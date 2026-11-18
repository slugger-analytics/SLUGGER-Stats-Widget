"""Landscape PDF of exactly the table on screen."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from display import ACCENT, INK, PANEL, format_cell, label


def generate_pdf(df, title, subtitle, selected_cols):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(LETTER),
                            leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("CustomTitle", parent=styles["Title"],
                                 textColor=colors.HexColor(INK), fontSize=14, alignment=1)
    subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"],
                                    textColor=colors.HexColor(ACCENT), fontSize=9, alignment=1)
    date_style = ParagraphStyle("Date", parent=styles["Normal"],
                                textColor=colors.HexColor(INK), fontSize=7, alignment=1)

    now = datetime.now(ZoneInfo("America/New_York"))
    elements = [
        Paragraph(now.strftime("Report Date: %B %d, %Y at %I:%M %p"), date_style),
        Spacer(1, 10), Paragraph(title, title_style), Spacer(1, 4),
        Paragraph(subtitle, subtitle_style), Spacer(1, 14),
    ]

    rows = [[format_cell(c, v) for c, v in zip(selected_cols, r)]
            for r in df[selected_cols].values.tolist()]
    data = [[label(c) for c in selected_cols]] + rows

    # Name and hand columns get fixed room, the stat columns share the rest.
    fixed = {"PLAYER": 120, "BATS": 40, "THROWS": 44, "ROLE": 36}
    fixed_total = sum(fixed[c] for c in selected_cols if c in fixed)
    stat_count = sum(1 for c in selected_cols if c not in fixed)
    stat_width = (720 - fixed_total) / stat_count if stat_count else 0
    col_widths = [fixed.get(c, stat_width) for c in selected_cols]
    body_size = 6 if len(selected_cols) > 22 else 7 if len(selected_cols) > 14 else 8

    table = Table(data, repeatRows=1, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(INK)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, 0), 7 if len(selected_cols) > 22 else 8),
        ("FONTSIZE", (0, 1), (-1, -1), body_size),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(PANEL)]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9ca3af")),
    ]))
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return buffer


def pdf_filename(prefix):
    return f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.pdf"
