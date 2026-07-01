"""
PDF-Export für Angebote (reportlab).
"""

from __future__ import annotations
import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable,
)
from reportlab.lib.enums import TA_RIGHT

PRIMARY = colors.HexColor("#2563eb")
LIGHT   = colors.HexColor("#f1f5f9")
INK     = colors.HexColor("#1e293b")
MUTED   = colors.HexColor("#94a3b8")


def _fmt_eur(n: float) -> str:
    s = f"{n:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s + " €"


def erstelle_angebots_pdf(
    *,
    angebot_nr: str,
    firmenname: str = "Ihr Unternehmen",
    kunde: str,
    projekt_name: str,
    positionen: list[dict],
    erstellt_am: datetime | None = None,
) -> bytes:
    """Gibt das Angebots-PDF als bytes zurück."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2.5 * cm, bottomMargin=2.5 * cm,
    )

    styles = getSampleStyleSheet()
    h1     = ParagraphStyle("h1",     parent=styles["Heading1"], textColor=PRIMARY, fontSize=18, spaceAfter=4)
    normal = ParagraphStyle("normal", parent=styles["Normal"],   fontSize=9,  textColor=INK, leading=13)
    small  = ParagraphStyle("small",  parent=styles["Normal"],   fontSize=8,  textColor=MUTED)
    right  = ParagraphStyle("right",  parent=styles["Normal"],   fontSize=9,  alignment=TA_RIGHT)
    bold9  = ParagraphStyle("bold9",  parent=styles["Normal"],   fontSize=9,  fontName="Helvetica-Bold")

    if erstellt_am is None:
        erstellt_am = datetime.now(timezone.utc)
    datum_str = erstellt_am.strftime("%d.%m.%Y")

    story = []

    # Header
    story.append(Paragraph(firmenname, h1))
    story.append(HRFlowable(width="100%", thickness=1, color=PRIMARY, spaceAfter=6))

    meta = [
        ["Angebot Nr.:", angebot_nr, "Datum:",   datum_str],
        ["Kunde:",       kunde,      "Projekt:", projekt_name],
    ]
    meta_table = Table(meta, colWidths=[3.5 * cm, 7 * cm, 2.5 * cm, 4.5 * cm])
    meta_table.setStyle(TableStyle([
        ("FONTSIZE",     (0, 0), (-1, -1), 9),
        ("FONTNAME",     (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",     (2, 0), (2, -1), "Helvetica-Bold"),
        ("TEXTCOLOR",    (0, 0), (-1, -1), INK),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 0.8 * cm))

    # Positionstabelle
    story.append(Paragraph("Leistungspositionen", bold9))
    story.append(Spacer(1, 0.3 * cm))

    header = ["Nr.", "Beschreibung", "Rolle", "Std.", "Satz €/h", "Summe"]
    rows   = [header]
    gesamt = 0.0

    for pos in positionen:
        summe = pos.get("summe") or (pos.get("stunden", 0) * pos.get("stundensatz", 0))
        gesamt += summe
        rows.append([
            str(pos.get("nr", "")),
            Paragraph(pos.get("beschreibung", ""), normal),
            pos.get("rolle", "–"),
            f"{pos.get('stunden', 0):.1f}",
            _fmt_eur(pos.get("stundensatz", 0)),
            _fmt_eur(summe),
        ])

    rows.append([
        "", "", "", "",
        Paragraph("<b>Gesamt (netto)</b>", right),
        Paragraph(f"<b>{_fmt_eur(gesamt)}</b>", right),
    ])

    col_widths = [1 * cm, 7.5 * cm, 3.5 * cm, 1.5 * cm, 2.5 * cm, 2.5 * cm]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  PRIMARY),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0),  9),
        ("BOTTOMPADDING", (0, 0), (-1, 0),  6),
        ("TOPPADDING",    (0, 0), (-1, 0),  6),
        ("FONTSIZE",      (0, 1), (-1, -1), 9),
        ("TEXTCOLOR",     (0, 1), (-1, -1), INK),
        ("ROWBACKGROUNDS",(0, 1), (-1, -2), [colors.white, LIGHT]),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("LINEABOVE",     (0, -1),(-1, -1), 1, PRIMARY),
        ("TOPPADDING",    (0, -1),(-1, -1), 8),
        ("GRID",          (0, 0), (-1, -2), 0.3, MUTED),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, PRIMARY),
    ]))
    story.append(table)
    story.append(Spacer(1, 1 * cm))

    # Footer
    story.append(HRFlowable(width="100%", thickness=0.5, color=MUTED, spaceBefore=4))
    story.append(Paragraph(
        "Alle Preise verstehen sich netto zzgl. der gesetzlichen Mehrwertsteuer. "
        "Dieses Angebot wurde mit EstimateIQ erstellt.",
        small,
    ))

    doc.build(story)
    return buf.getvalue()
