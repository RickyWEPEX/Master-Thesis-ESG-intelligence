"""ESG-Nachhaltigkeitsbericht PDF-Export (FA-5.2).

Erstellt einen vollstaendigen CSRD/ESRS-konformen Nachhaltigkeitsbericht als PDF mit:
- Doppelter Wesentlichkeitsanalyse (alle 10 ESRS-Standards, ESRS 1 IG 1)
- Narrativer Interpretation aller KPIs (aus AssessmentErgebnis)
- Offenlegungen fuer alle Standards E1-G1 (wesentlich und nicht wesentlich)
- CSRD-Compliance-Erklaerung (alle ESRS-Standards)
- EU AI Act Transparency-Deklaration (Art. 13 / 50)
- Priorisierte Handlungsempfehlungen
"""
from __future__ import annotations

import io
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_W, _H = A4

# -- Farbpalette ---------------------------------------------------------------
_NAVY = colors.HexColor("#0d1b4b")
_BLUE = colors.HexColor("#1565c0")
_GREEN = colors.HexColor("#2e7d32")
_AMBER = colors.HexColor("#e65100")
_RED = colors.HexColor("#c62828")
_LIGHT_BLUE = colors.HexColor("#e3f2fd")
_LIGHT_GREEN = colors.HexColor("#e8f5e9")
_LIGHT_AMBER = colors.HexColor("#fff3e0")
_LIGHT_RED = colors.HexColor("#ffebee")
_GREY_BG = colors.HexColor("#f5f5f5")
_GREY_LINE = colors.HexColor("#bdbdbd")

_AMPEL_COLOR = {"GRUEN": _GREEN, "GELB": _AMBER, "ROT": _RED, "NEUTRAL": colors.grey}
_AMPEL_BG = {"GRUEN": _LIGHT_GREEN, "GELB": _LIGHT_AMBER, "ROT": _LIGHT_RED, "NEUTRAL": _GREY_BG}
_AMPEL_LABEL = {"GRUEN": "GRUEN", "GELB": "GELB", "ROT": "ROT", "NEUTRAL": "n/a"}


def _styles() -> dict:
    s = getSampleStyleSheet()
    base = s["Normal"]
    return {
        "cover_title": ParagraphStyle("ct", parent=base, fontSize=22, leading=28,
                                      textColor=_NAVY, spaceAfter=4, fontName="Helvetica-Bold"),
        "cover_sub": ParagraphStyle("cs", parent=base, fontSize=12, leading=16,
                                    textColor=_BLUE, spaceAfter=3),
        "cover_meta": ParagraphStyle("cm", parent=base, fontSize=9, leading=12,
                                     textColor=colors.grey),
        "h1": ParagraphStyle("h1", parent=base, fontSize=13, leading=17,
                              textColor=_NAVY, spaceBefore=14, spaceAfter=5,
                              fontName="Helvetica-Bold"),
        "h2": ParagraphStyle("h2", parent=base, fontSize=10.5, leading=14,
                              textColor=_BLUE, spaceBefore=8, spaceAfter=3,
                              fontName="Helvetica-Bold"),
        "h3": ParagraphStyle("h3", parent=base, fontSize=9.5, leading=13,
                              textColor=_NAVY, spaceBefore=5, spaceAfter=2,
                              fontName="Helvetica-Bold"),
        "body": ParagraphStyle("body", parent=base, fontSize=9, leading=13,
                               spaceAfter=5, firstLineIndent=0),
        "body_indent": ParagraphStyle("bi", parent=base, fontSize=9, leading=13,
                                      spaceAfter=3, leftIndent=10),
        "small": ParagraphStyle("sm", parent=base, fontSize=7.5, leading=10,
                                textColor=colors.grey),
        "ampel_gruen": ParagraphStyle("ag", parent=base, fontSize=10,
                                      textColor=_GREEN, fontName="Helvetica-Bold"),
        "ampel_gelb": ParagraphStyle("ay", parent=base, fontSize=10,
                                     textColor=_AMBER, fontName="Helvetica-Bold"),
        "ampel_rot": ParagraphStyle("ar", parent=base, fontSize=10,
                                    textColor=_RED, fontName="Helvetica-Bold"),
        "bullet": ParagraphStyle("blt", parent=base, fontSize=9, leading=12,
                                 leftIndent=12, spaceAfter=2),
        "disclaimer": ParagraphStyle("dis", parent=base, fontSize=7.5, leading=10,
                                     textColor=colors.grey, borderWidth=0.5,
                                     borderColor=colors.lightgrey, borderPadding=4),
        # Tabellenzellen: brechen automatisch um (loest Zellueberlauf)
        "cell": ParagraphStyle("cell", parent=base, fontSize=8, leading=10),
        "cell_head": ParagraphStyle("cellh", parent=base, fontSize=8, leading=10,
                                    textColor=colors.white, fontName="Helvetica-Bold"),
    }


def _ts(header=True) -> TableStyle:
    cmds = [
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, _GREY_BG]),
        ("GRID", (0, 0), (-1, -1), 0.3, _GREY_LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        cmds.append(("BACKGROUND", (0, 0), (-1, 0), _NAVY))
    return TableStyle(cmds)


def _esc(text: Any) -> str:
    """HTML-escaped String fuer ReportLab-Paragraph (verhindert Markup-Fehler)."""
    return (str(text) if text is not None else "-").replace(
        "&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cell(text: Any, style: ParagraphStyle) -> Paragraph:
    """Wandelt Zellinhalt in umbruchfaehigen Paragraph (loest Zellueberlauf)."""
    if isinstance(text, Paragraph):
        return text
    return Paragraph(_esc(text), style)


def _color_cell(text: Any, hexcolor: colors.Color, style: ParagraphStyle,
                bold: bool = True) -> Paragraph:
    """Farbig hervorgehobene Zelle (z.B. Ampel-/Status-Spalte)."""
    hx = hexcolor.hexval()[2:] if hasattr(hexcolor, "hexval") else "000000"
    inner = _esc(text)
    if bold:
        inner = f"<b>{inner}</b>"
    return Paragraph(f'<font color="#{hx}">{inner}</font>', style)


def _mk_table(rows: list, col_widths: list, S: dict, header: bool = True,
              extra_style: list | None = None) -> Table:
    """Baut eine Tabelle mit automatisch umbrechenden Paragraph-Zellen.

    Rohe Strings werden in Paragraphs gewrappt; bereits gewrappte Paragraph-
    Objekte (z.B. farbige Zellen) bleiben erhalten.
    """
    cell_s, head_s = S["cell"], S["cell_head"]
    data = []
    for r_idx, row in enumerate(rows):
        style = head_s if (header and r_idx == 0) else cell_s
        data.append([_cell(c, style) for c in row])
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    ts = _ts(header)
    if extra_style:
        for cmd in extra_style:
            ts.add(*cmd)
    t.setStyle(ts)
    return t


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        if abs(value) >= 1000:
            return f"{value:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(value)


def _wrap(text: str, width: int = 120) -> str:
    """Bricht langen Text fuer PDF-Tabellenzellen um."""
    return "\n".join(textwrap.wrap(str(text), width)) if text else "-"


def _narrative_box(story: list, text: str, S: dict, bg: colors.Color = None):
    """Rendert einen Textkaster mit optionalem Hintergrund."""
    if not text or text.startswith("_"):
        return
    clean = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    p = Paragraph(clean, S["body"])
    if bg:
        data = [[p]]
        t = Table(data, colWidths=[16 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("BOX", (0, 0), (-1, -1), 0.5, _GREY_LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(t)
    else:
        story.append(p)
    story.append(Spacer(1, 0.2 * cm))


_STANDARD_LABELS = {
    "E1": "ESRS E1 — Klimawandel",
    "E2": "ESRS E2 — Umweltverschmutzung",
    "E3": "ESRS E3 — Wasser- und Meeresressourcen",
    "E4": "ESRS E4 — Biodiversitaet und Oekosysteme",
    "E5": "ESRS E5 — Ressourcennutzung und Kreislaufwirtschaft",
    "S1": "ESRS S1 — Eigene Belegschaft",
    "S2": "ESRS S2 — Arbeitskraefte in der Wertschoepfungskette",
    "S3": "ESRS S3 — Betroffene Gemeinschaften",
    "S4": "ESRS S4 — Verbraucher und Endnutzer",
    "G1": "ESRS G1 — Unternehmenspolitik / Governance",
}


def _kpi_table_by_standard(story: list, extracted: list, standard_prefix: str, S: dict):
    """KPI-Tabelle fuer einen beliebigen Standard (gefiltert nach ID-Praefix)."""
    rows = [["Datenpunkt", "DR", "Wert", "Einheit"]]
    for e in extracted:
        if e.id.startswith(standard_prefix + "-") and e.present and e.datatype != "narrative":
            rows.append([e.name_de, e.dr, _fmt(e.value), e.unit or "—"])
    if len(rows) > 1:
        story.append(_mk_table(rows, [7.5 * cm, 2 * cm, 3 * cm, 4 * cm], S))
        story.append(Spacer(1, 0.3 * cm))
    else:
        story.append(Paragraph("Keine numerischen Datenpunkte vorhanden.", S["body"]))


def _narrative_dps(story: list, extracted: list, standard_prefix: str, S: dict):
    """Zeigt narrative Datenpunkte eines Standards."""
    for e in extracted:
        if e.id.startswith(standard_prefix + "-") and e.present and e.datatype == "narrative":
            story.append(Paragraph(e.name_de, S["h3"]))
            _narrative_box(story, str(e.value), S, bg=_LIGHT_BLUE)


def _kpi_table(story: list, extracted: list, categories: list, S: dict):
    rows = [["Datenpunkt", "Wert", "Einheit", "Konfidenz"]]
    for e in extracted:
        if e.category in categories and e.datatype != "narrative" and e.present:
            rows.append([
                e.name_de, _fmt(e.value), e.unit, f"{e.confidence:.2f}",
            ])
    if len(rows) > 1:
        story.append(_mk_table(rows, [9 * cm, 3 * cm, 2.5 * cm, 2 * cm], S))
        story.append(Spacer(1, 0.3 * cm))


def _section_header(story, title, S):
    story.append(HRFlowable(width="100%", thickness=1.5, color=_NAVY, spaceAfter=3))
    story.append(Paragraph(title, S["h1"]))


# =============================================================================

def build_pdf_bytes(
    company_data: dict,
    extracted: list,
    validation_issues: list,
    compliance,
    report_markdown: str,
    elapsed_seconds: float,
    backend: str,
    assessment=None,
    materiality=None,
) -> bytes:
    """Erstellt den vollstaendigen ESG-Lagebericht als PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title="CSRD/ESRS Nachhaltigkeitsbericht",
        author="KI-Agenten-Framework (Weiß, 2025/2026)",
    )
    S = _styles()
    company = company_data.get("company", {})
    co_name = company.get("name", "n/a")
    year = company.get("reporting_year", "n/a")
    story = []

    # =========================================================================
    # TITELSEITE
    # =========================================================================
    story.append(Spacer(1, 1.2 * cm))

    # Logobereich (Text-Ersatz)
    logo_data = [[Paragraph(
        f"<font color='#0d1b4b'><b>ESG LAGEBERICHT</b></font>",
        ParagraphStyle("lg", parent=getSampleStyleSheet()["Normal"],
                       fontSize=8, textColor=_NAVY, fontName="Helvetica-Bold")
    )]]
    logo_t = Table(logo_data, colWidths=[16 * cm])
    logo_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _LIGHT_BLUE),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(logo_t)
    story.append(Spacer(1, 0.8 * cm))

    story.append(Paragraph(co_name, S["cover_title"]))
    story.append(Paragraph(
        f"Nachhaltigkeitsoffenlegung nach CSRD / ESRS (E1–G1, alle Standards)", S["cover_sub"]
    ))
    story.append(Paragraph(
        f"Berichtsjahr {year} | Erstellt {datetime.now(timezone.utc).strftime('%d.%m.%Y')}",
        S["cover_meta"]
    ))
    story.append(HRFlowable(width="100%", thickness=2, color=_NAVY, spaceBefore=10, spaceAfter=10))

    # Metadaten-Tabelle
    meta_rows = [
        ["Unternehmen", co_name],
        ["Sektor", company.get("sector", "n/a")],
        ["Land", company.get("country", "n/a")],
        ["Berichtsjahr", str(year)],
        ["Rahmenwerk", "CSRD / ESRS E1–G1 (Amended Exposure Drafts, Juli 2025)"],
        ["Compliance-Status", f"{compliance.status} — {compliance.completeness_rate * 100:.0f}% Pflichtdatenpunkte"],
        ["Extraktions-Backend", backend],
        ["Verarbeitungszeit", f"{elapsed_seconds} s"],
        ["Erstellt am", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")],
    ]
    if assessment:
        meta_rows.insert(5, ["Klimaperformance (Ampel)", assessment.gesamtampel])

    meta_wrapped = [
        [Paragraph(f"<b>{_esc(k)}</b>", S["cell"]), _cell(v, S["cell"])]
        for k, v in meta_rows
    ]
    story.append(_mk_table(meta_wrapped, [5 * cm, 11.5 * cm], S, header=False))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(
        "Forschungsprototyp — Design Science Research (Frankfurt School of Finance & Management, 2025/2026). "
        "Synthetische Daten. Alle Angaben vor produktivem Einsatz fachlich zu pruefen. "
        "KI-generierte Inhalte sind entsprechend gekennzeichnet (EU AI Act Art. 50).",
        S["small"]
    ))
    story.append(PageBreak())

    # =========================================================================
    # EXECUTIVE SUMMARY
    # =========================================================================
    _section_header(story, "Executive Summary", S)

    # -- Einleitung -----------------------------------------------------------
    story.append(Paragraph(
        f"Der vorliegende Nachhaltigkeitsbericht der {co_name} dokumentiert die "
        f"ESG-Offenlegungen fuer das Berichtsjahr {year} gemaess CSRD und den "
        f"European Sustainability Reporting Standards (ESRS, Amended Exposure Drafts "
        f"Juli 2025). Grundlage ist die doppelte Wesentlichkeitsanalyse (ESRS 1, IRO-1), "
        f"die bestimmt, zu welchen der 10 ESRS-Standards Offenlegungen zu machen sind. "
        f"Der Bericht wurde durch ein KI-Agenten-Framework erstellt und ist vor "
        f"produktivem Einsatz durch externe Pruefer zu validieren (CSRD Art. 34).",
        S["body"]
    ))
    story.append(Spacer(1, 0.3 * cm))

    # -- ESG-Gesamtstatus-Tabelle (alle wesentlichen Standards) ---------------
    story.append(Paragraph("ESG-Gesamtueberblick — Alle Standards im Sektorvergleich", S["h2"]))

    # Gesamt-ESG-Ampel berechnen
    if assessment and assessment.kpi_bewertungen:
        alle_bew = assessment.kpi_bewertungen
        rot_ges = sum(1 for b in alle_bew if b.ampel == "ROT")
        gelb_ges = sum(1 for b in alle_bew if b.ampel == "GELB")
        gruen_ges = sum(1 for b in alle_bew if b.ampel == "GRUEN")
        if rot_ges >= 2:
            gesamt_esg = "ROT"
        elif rot_ges >= 1 or gelb_ges >= 4:
            gesamt_esg = "GELB"
        elif gruen_ges >= len(alle_bew) * 0.7:
            gesamt_esg = "GRUEN"
        else:
            gesamt_esg = "GELB"
        esg_farbe = _AMPEL_COLOR.get(gesamt_esg, colors.grey)
        story.append(Paragraph(
            f"ESG-Gesamtstatus: {gesamt_esg} | "
            f"KPIs: {gruen_ges}x GRUEN / {gelb_ges}x GELB / {rot_ges}x ROT | "
            f"Geprueft: {len(alle_bew)} Kennzahlen ueber alle wesentlichen Standards",
            S[f"ampel_{gesamt_esg.lower()}"] if gesamt_esg in ("GRUEN","GELB","ROT") else S["body"]
        ))
        story.append(Spacer(1, 0.2 * cm))

    # Tabelle: Standard / Ampel-Status / Kern-KPI / Interpretation / Handlungsbedarf
    bew_by_std: dict = {}
    if assessment:
        for b in assessment.kpi_bewertungen:
            std = b.dp_id.split("-")[0]
            bew_by_std.setdefault(std, []).append(b)

    by_id_ex = {e.id: e for e in extracted}
    _KERN_KPI = {
        "E1": ("E1-DP-007", "THG-Emissionen gesamt", "tCO2e"),
        "E2": ("E2-DP-001", "NOx-Emissionen", "kg"),
        "E3": ("E3-DP-001", "Wasserverbrauch", "m3"),
        "E4": ("E4-DP-001", "Flaechennutzung", "m2"),
        "E5": ("E5-DP-002", "Recyclingquote", "%"),
        "S1": ("S1-DP-002", "Gender Pay Gap", "%"),
        "S2": ("S2-DP-003", "Hochrisikolieferanten", "%"),
        "S3": ("S3-DP-002", "Beschwerden", "Anzahl"),
        "S4": ("S4-DP-001", "Kundenbeschwerden/1000", ""),
        "G1": ("G1-DP-002", "Antikorruptionstraining", "%"),
    }

    def _std_ampel(bewertungen: list) -> str:
        """Konsistente Ampelberechnung je Standard (identisch zur AssessmentAgent-Logik).

        ROT:     >= 30% der bewerteten KPIs sind ROT
        GRUEN:   >= 70% der bewerteten KPIs sind GRUEN
        GELB:    sonst
        NEUTRAL: alle KPIs fehlen (keine Datenbasis)
        """
        if not bewertungen:
            return "NEUTRAL"
        bewertet = [b for b in bewertungen if b.ampel != "NEUTRAL"]
        if not bewertet:
            return "NEUTRAL"
        n = len(bewertet)
        rot = sum(1 for b in bewertet if b.ampel == "ROT")
        gruen = sum(1 for b in bewertet if b.ampel == "GRUEN")
        if rot / n >= 0.30:
            return "ROT"
        if gruen / n >= 0.70:
            return "GRUEN"
        return "GELB"

    overview_rows = [["Standard", "Status", "Kern-KPI", "Wert", "Wichtigste Erkenntnis"]]
    if materiality:
        for t in materiality.themen:
            std_id = t.id
            bewertungen = bew_by_std.get(std_id, [])
            kern = _KERN_KPI.get(std_id)
            kern_wert = "—"
            kern_label = "—"
            if kern:
                dp = by_id_ex.get(kern[0])
                if dp and dp.present:
                    kern_wert = f"{_fmt(dp.value)} {kern[2]}".strip()
                kern_label = kern[1]

            if not t.wesentlich:
                status_cell = _color_cell("nicht wesentlich", colors.grey, S["cell"], bold=False)
                erkenntnis = "Nicht berichtspflichtig; Daten zur Transparenz ausgewiesen."
            elif not bewertungen:
                status_cell = _color_cell("DATEN FEHLEN", _AMBER, S["cell"])
                erkenntnis = "Keine Eingabedaten vorhanden — Bewertung nicht moeglich."
            else:
                ampel_std = _std_ampel(bewertungen)
                rot_bew   = [b for b in bewertungen if b.ampel == "ROT"]
                gelb_bew  = [b for b in bewertungen if b.ampel == "GELB"]
                gruen_bew = [b for b in bewertungen if b.ampel == "GRUEN"]
                neut_bew  = [b for b in bewertungen if b.ampel == "NEUTRAL"]

                if ampel_std == "NEUTRAL":
                    status_cell = _color_cell(
                        f"DATEN FEHLEN ({len(neut_bew)} KPIs ohne Wert)",
                        _AMBER, S["cell"]
                    )
                    erkenntnis = (
                        f"Alle {len(neut_bew)} KPIs dieses Standards haben keine Eingabedaten. "
                        "Keine belastbare Aussage moeglich. Daten im naechsten Berichtszyklus erheben."
                    )
                else:
                    fehlt_hinweis = (
                        f" ({len(neut_bew)} KPIs ohne Daten)" if neut_bew else ""
                    )
                    status_cell = _color_cell(
                        f"{ampel_std} ({len(gruen_bew)}G/{len(gelb_bew)}Y/{len(rot_bew)}R){fehlt_hinweis}",
                        _AMPEL_COLOR.get(ampel_std, colors.grey), S["cell"]
                    )
                    # Wichtigste Erkenntnis: schlechtester bewerteter KPI
                    if rot_bew:
                        worst = rot_bew[0]
                        erkenntnis = f"{worst.name_de}: {worst.interpretation}"
                    elif gelb_bew:
                        worst = gelb_bew[0]
                        erkenntnis = f"{worst.name_de}: {worst.interpretation}"
                    else:
                        erkenntnis = (
                            f"Alle {len(gruen_bew)} bewerteten KPIs im gruenen Bereich: " +
                            ", ".join(b.name_de for b in gruen_bew[:3]) + "."
                            + (f" {len(neut_bew)} KPIs ohne Datenbasis." if neut_bew else "")
                        )

            overview_rows.append([
                f"{t.standard}\n{t.name_de}",
                status_cell,
                kern_label,
                kern_wert,
                erkenntnis,
            ])

    story.append(_mk_table(
        overview_rows, [3.2 * cm, 2.8 * cm, 3 * cm, 2.2 * cm, 5.3 * cm], S
    ))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        "Status-Legende: GRUEN = besser als Sektormedian | GELB = Handlungsbedarf | "
        "ROT = kritischer Handlungsbedarf | (G/Y/R) = Anzahl GRUEN/GELB/ROT-KPIs je Standard.",
        S["small"]
    ))
    story.append(Spacer(1, 0.4 * cm))

    # -- Klimaperformance E1 (ausfuehrlich) -----------------------------------
    story.append(Paragraph("ESRS E1 — Klimawandel: Detailbewertung", S["h2"]))
    if assessment:
        ampel_bg = _AMPEL_BG.get(assessment.gesamtampel, _GREY_BG)
        story.append(Paragraph(
            f"Gesamtbewertung Klimaperformance: {assessment.gesamtampel}",
            S[f"ampel_{assessment.gesamtampel.lower()}"]
            if assessment.gesamtampel in ("GRUEN","GELB","ROT") else S["body"]
        ))
        sek = assessment.lagebericht_abschnitte
        _narrative_box(story, sek.get("gesamtbewertung", ""), S, bg=ampel_bg)
        story.append(Spacer(1, 0.1 * cm))

    # E1-KPI-Tabelle mit Ampel
    e1_bew = bew_by_std.get("E1", [])
    if e1_bew:
        e1_rows = [["KPI", "Wert", "Einheit", "Sektormedian", "Ampel", "Interpretation"]]
        for b in e1_bew:
            e1_rows.append([
                b.name_de,
                _fmt(b.wert) if b.wert is not None else "—",
                b.einheit,
                _fmt(b.sektor_p50) if b.sektor_p50 else "—",
                _color_cell(_AMPEL_LABEL.get(b.ampel, b.ampel),
                            _AMPEL_COLOR.get(b.ampel, colors.grey), S["cell"]),
                b.interpretation,
            ])
        story.append(_mk_table(
            e1_rows, [3.5 * cm, 1.8 * cm, 1.5 * cm, 2 * cm, 1.5 * cm, 6.2 * cm], S
        ))
    story.append(Spacer(1, 0.3 * cm))

    # -- Weitere wesentliche Standards (kompakt mit Interpretation) -----------
    if materiality:
        andere_wes = [t for t in materiality.themen
                      if t.wesentlich and t.standard != "ESRS E1"]
        if andere_wes:
            story.append(Paragraph(
                "Weitere wesentliche Standards — Kernbefunde und Massnahmen", S["h2"]
            ))
            for t in andere_wes:
                bewertungen = bew_by_std.get(t.id, [])
                rot   = [b for b in bewertungen if b.ampel == "ROT"]
                gelb  = [b for b in bewertungen if b.ampel == "GELB"]
                gruen = [b for b in bewertungen if b.ampel == "GRUEN"]
                neut  = [b for b in bewertungen if b.ampel == "NEUTRAL"]
                ampel_std = _std_ampel(bewertungen)
                bg = {"ROT": _LIGHT_RED, "GELB": _LIGHT_AMBER, "GRUEN": _LIGHT_GREEN}.get(ampel_std, _LIGHT_AMBER)

                fehlt_hint = f" | {len(neut)}x ohne Daten" if neut else ""
                story.append(Paragraph(
                    f"{t.standard} — {t.name_de}  |  Status: {ampel_std}  |  "
                    f"{len(gruen)}x GRUEN / {len(gelb)}x GELB / {len(rot)}x ROT{fehlt_hint}",
                    S[f"ampel_{ampel_std.lower()}"] if ampel_std in ("GRUEN","GELB","ROT") else S["body"]
                ))

                interp_parts = []
                if ampel_std == "NEUTRAL":
                    interp_parts.append(
                        "Keine belastbare Aussage moeglich: Alle Datenpunkte dieses Standards "
                        "fehlen in den Eingabedaten. Die folgende Tabelle zeigt die erwarteten "
                        "Kennzahlen mit Sektormedian als Orientierung."
                    )
                else:
                    if rot:
                        for b in rot:
                            interp_parts.append(
                                f"Kritisch — {b.name_de} ({_fmt(b.wert)} {b.einheit}, "
                                f"Median {_fmt(b.sektor_p50)} {b.einheit}): {b.interpretation} "
                                f"Massnahme: {b.empfehlung}"
                            )
                    if gelb:
                        for b in gelb[:2]:
                            interp_parts.append(
                                f"Handlungsbedarf — {b.name_de} ({_fmt(b.wert)} {b.einheit}): "
                                f"{b.interpretation}"
                            )
                    if gruen and not rot and not gelb:
                        interp_parts.append(
                            "Alle geprueften Kennzahlen im gruenen Bereich: " +
                            ", ".join(f"{b.name_de} ({_fmt(b.wert)} {b.einheit})" for b in gruen[:3]) + "."
                        )
                    if neut:
                        interp_parts.append(
                            f"Hinweis: {len(neut)} Kennzahl(en) ohne Eingabedaten — "
                            "keine belastbare Aussage moeglich: " +
                            ", ".join(b.name_de for b in neut) + "."
                        )
                _narrative_box(story, " | ".join(interp_parts) if interp_parts else "Keine Daten.", S, bg=bg)
                story.append(Spacer(1, 0.15 * cm))

    story.append(Spacer(1, 0.2 * cm))

    # -- Top-Empfehlungen ---
    story.append(Paragraph("Top-Handlungsempfehlungen", S["h2"]))
    if assessment and assessment.handlungsempfehlungen:
        for emp in assessment.handlungsempfehlungen[:5]:
            bg = _LIGHT_RED if "HOCH" in emp else _LIGHT_AMBER if "MITTEL" in emp else _GREY_BG
            _narrative_box(story, emp, S, bg=bg)

    # -- Compliance ---
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        f"Compliance-Status: {compliance.status} | "
        f"{compliance.present_mandatory}/{compliance.total_mandatory} Pflichtangaben "
        f"({compliance.completeness_rate * 100:.0f}%) | "
        f"Wesentliche Standards: {len(materiality.wesentliche_themen) if materiality else '—'} von 10",
        S["body"]
    ))
    story.append(PageBreak())

    # =========================================================================
    # CSRD / ESRS 2: GOVERNANCE UND STRATEGIE (Allgemeine Angaben)
    # =========================================================================
    _section_header(story, "1  Governance und Strategie (ESRS 2)", S)
    story.append(Paragraph(
        "Gemaess ESRS 2 (Allgemeine Angaben) sind Angaben zu Governance-Strukturen, "
        "Strategie und Stakeholder-Engagement erforderlich. Die nachfolgenden Angaben "
        "entsprechen den Mindestanforderungen fuer kleine Institute gemaess MaRisk-Novelle 9.",
        S["body"]
    ))

    gov_rows = [
        ["Anforderung (ESRS 2)", "Status", "Angabe"],
        ["GOV-1: Governance-Strukturen und -prozesse",
         "Vorhanden",
         "Nachhaltigkeitskomitee auf Vorstandsebene; jaehrliche Berichterstattung."],
        ["GOV-2: Informationen an Governance-Organe",
         "Vorhanden",
         "Quartalsweise Klimaberichte an Vorstand und Aufsichtsrat."],
        ["SBM-1: Strategie, Geschaeftsmodell, Wertschoepfungskette",
         "Partiell",
         "Fokus: Finanzierungsportfolio, Einlagengeschaeft, Beratungsleistungen."],
        ["SBM-2: Interessen und Meinungen der Stakeholder",
         "Partiell",
         "Jaehrliche Wesentlichkeitsanalyse; Stakeholder: Kunden, Regulatoren, Investoren."],
        ["SBM-3: Materielle Auswirkungen, Risiken und Chancen",
         "Vorhanden",
         "Klimarisiko-Screening des Kreditportfolios; physische und transitorische Risiken erfasst."],
        ["IRO-1: Wesentlichkeitsbewertung (Double Materiality)",
         "Vorhanden",
         "Ausgangspunkt: E1 (Klimawandel) als wesentlicher Standard identifiziert."],
    ]
    # Status-Spalte farbig wrappen
    for r in gov_rows[1:]:
        c = _GREEN if r[1] == "Vorhanden" else _AMBER if r[1] == "Partiell" else _RED
        r[1] = _color_cell(r[1], c, S["cell"])
    story.append(_mk_table(gov_rows, [5 * cm, 2.5 * cm, 9 * cm], S))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph(
        "Hinweis: Die vollstaendige CSRD-Berichterstattung erfordert zusaetzlich ESRS E2-E5 "
        "(weitere Umweltthemen), ESRS S1-S4 (Soziales) und ESRS G1 (Unternehmensethik). "
        "Der vorliegende Prototyp adressiert schwerpunktmaessig die als wesentlich "
        "identifizierten Standards (siehe Wesentlichkeitsanalyse).",
        S["small"]
    ))
    story.append(PageBreak())

    # =========================================================================
    # DOPPELTE WESENTLICHKEITSANALYSE (ESRS 1 / IRO-1)
    # =========================================================================
    _section_header(story, "2  Doppelte Wesentlichkeitsanalyse (ESRS 1, IRO-1)", S)

    if materiality is not None:
        _narrative_box(story, materiality.zusammenfassung, S, bg=_LIGHT_BLUE)
        story.append(Paragraph(
            f"Methode: {materiality.methode} | Wesentlichkeitsschwelle: "
            f"Score &ge; {materiality.schwellenwert} (Skala 1-5). "
            f"Ein Thema gilt als wesentlich, wenn die Impact- ODER die Financial-Dimension "
            f"den Schwellenwert erreicht (ESRS 1, Kapitel 3.4).",
            S["small"]
        ))
        story.append(Spacer(1, 0.3 * cm))

        mat_rows = [["ESRS-Thema", "Impact", "Financial", "Wesentlich", "Dimension", "Quelle"]]
        for t in materiality.themen:
            wes = _color_cell("JA", _GREEN, S["cell"]) if t.wesentlich \
                else _color_cell("nein", colors.grey, S["cell"], bold=False)
            mat_rows.append([
                f"{t.name_de} ({t.standard})",
                f"{t.impact_score}",
                f"{t.financial_score}",
                wes,
                t.dimension,
                t.quelle,
            ])
        story.append(_mk_table(
            mat_rows, [5.5 * cm, 1.8 * cm, 1.9 * cm, 2 * cm, 2 * cm, 3.3 * cm], S
        ))
        story.append(Spacer(1, 0.3 * cm))
        # Sub-Topics E1
        e1_thema = next((t for t in materiality.themen if t.standard == "ESRS E1"), None)
        if e1_thema and e1_thema.sub_topic_bewertungen:
            story.append(Spacer(1, 0.3 * cm))
            story.append(Paragraph(
                "Sub-Topics ESRS E1 (zweite Bewertungsebene, IG 1 Appendix A)", S["h2"]
            ))
            st_rows = [["Sub-Topic", "Impact", "Financial", "Wesentlich", "Offenlegungs-DRs"]]
            for st in e1_thema.sub_topic_bewertungen:
                if st["status"] == "bewertet":
                    w = (_color_cell("JA", _GREEN, S["cell"]) if st["wesentlich"]
                         else _color_cell("nein", colors.grey, S["cell"], bold=False))
                    st_rows.append([
                        st["name_de"],
                        f"{st['impact_score']}" if st["impact_score"] else "—",
                        f"{st['financial_score']}" if st["financial_score"] else "—",
                        w,
                        st.get("appendix_a_ref", ""),
                    ])
            if len(st_rows) > 1:
                story.append(_mk_table(
                    st_rows, [4.5 * cm, 1.5 * cm, 1.8 * cm, 2 * cm, 6.7 * cm], S
                ))

        story.append(Paragraph(
            "Die detaillierten Offenlegungen zu jedem Standard — wesentlich wie nicht "
            "wesentlich — sind in den nachfolgenden standardspezifischen Kapiteln dieses "
            "Berichts dokumentiert.",
            S["small"]
        ))
    else:
        story.append(Paragraph(
            "Wesentlichkeitsanalyse nicht verfuegbar. ESRS E1 (Klimawandel) wird als "
            "wesentlich angenommen.", S["body"]
        ))
    story.append(PageBreak())

    # =========================================================================
    # KLIMASTRATEGIE (E1-1 / E1-2)
    # =========================================================================
    _section_header(story, "3  Klimastrategie und Transitionsplan (E1-1, E1-2)", S)

    if assessment:
        sek = assessment.lagebericht_abschnitte
        _narrative_box(story, sek.get("klimastrategie", ""), S)

    story.append(Paragraph("E1-1: Transitionsplan zur Klimaschutzminderung", S["h2"]))
    transition = next((e for e in extracted if e.id == "E1-DP-029"), None)
    if transition and transition.present:
        _narrative_box(story, str(transition.value), S, bg=_LIGHT_BLUE)
    else:
        story.append(Paragraph("Nicht verfuegbar (Pflichtangabe fehlt).", S["body"]))

    story.append(Paragraph("E1-2: Klimakonzepte und -strategie", S["h2"]))
    policies = next((e for e in extracted if e.id == "E1-DP-030"), None)
    if policies and policies.present:
        _narrative_box(story, str(policies.value), S, bg=_LIGHT_BLUE)
    else:
        story.append(Paragraph("Nicht verfuegbar.", S["body"]))

    # =========================================================================
    # MASSNAHMEN (E1-3)
    # =========================================================================
    _section_header(story, "4  Massnahmen und Ressourcen (E1-3)", S)
    actions = next((e for e in extracted if e.id == "E1-DP-031"), None)
    if actions and actions.present:
        _narrative_box(story, str(actions.value), S, bg=_LIGHT_BLUE)
    else:
        story.append(Paragraph("Nicht verfuegbar.", S["body"]))

    # =========================================================================
    # KLIMARISIKEN & CHANCEN (E1-SBM-3)
    # =========================================================================
    _section_header(story, "5  Klimabezogene Risiken und Chancen (E1-SBM-3)", S)

    if assessment:
        _narrative_box(story, sek.get("klimarisiken", ""), S)

    story.append(Paragraph("Physische Risiken", S["h2"]))
    phys = next((e for e in extracted if e.id == "E1-DP-032"), None)
    if phys and phys.present:
        _narrative_box(story, str(phys.value), S, bg=_LIGHT_AMBER)

    story.append(Paragraph("Transitorische Risiken", S["h2"]))
    trans = next((e for e in extracted if e.id == "E1-DP-033"), None)
    if trans and trans.present:
        _narrative_box(story, str(trans.value), S, bg=_LIGHT_AMBER)

    story.append(Paragraph("Klimachancen", S["h2"]))
    opp = next((e for e in extracted if e.id == "E1-DP-034"), None)
    if opp and opp.present:
        _narrative_box(story, str(opp.value), S, bg=_LIGHT_GREEN)

    if assessment:
        # Risiken-Liste
        if assessment.risiken:
            story.append(Paragraph("Identifizierte Risiken (Sektorvergleich):", S["h3"]))
            for r in assessment.risiken:
                story.append(Paragraph(f"- {r}", S["bullet"]))
            story.append(Spacer(1, 0.2 * cm))
        if assessment.chancen:
            story.append(Paragraph("Identifizierte Chancen:", S["h3"]))
            for c in assessment.chancen:
                story.append(Paragraph(f"+ {c}", S["bullet"]))

    story.append(PageBreak())

    # =========================================================================
    # ENERGIE (E1-4) MIT INTERPRETATION
    # =========================================================================
    _section_header(story, "6  Energieverbrauch und -mix (E1-4)", S)

    if assessment:
        _narrative_box(story, sek.get("energie", ""), S)

    _kpi_table(story, extracted, ["energy"], S)

    # Energie-KPI-Bewertung
    if assessment:
        en_bew = next((b for b in assessment.kpi_bewertungen if b.dp_id == "E1-DP-017"), None)
        if en_bew:
            story.append(Paragraph("Bewertung Anteil erneuerbarer Energie:", S["h3"]))
            _narrative_box(story, en_bew.interpretation, S,
                           bg=_AMPEL_BG.get(en_bew.ampel, _GREY_BG))
            if en_bew.empfehlung:
                story.append(Paragraph(f"Empfehlung: {en_bew.empfehlung}", S["small"]))

    # =========================================================================
    # THG-EMISSIONEN (E1-6) MIT INTERPRETATION
    # =========================================================================
    _section_header(story, "7  Brutto-THG-Emissionen Scope 1/2/3 (E1-6)", S)

    if assessment:
        _narrative_box(story, sek.get("thg_emissionen", ""), S)

    # Scope-Uebersichtstabelle
    scope_map = {"E1-DP-001": "Scope 1", "E1-DP-003": "Scope 2 (standortbasiert)",
                 "E1-DP-004": "Scope 2 (marktbasiert)", "E1-DP-005": "Scope 3 gesamt",
                 "E1-DP-006": "Total (standortbasiert)", "E1-DP-007": "Total (marktbasiert)"}
    scope_rows = [["Scope", "tCO2e", "Anteil am Total (marktbasiert)"]]
    total_market = next((e for e in extracted if e.id == "E1-DP-007"), None)
    total_val = total_market.value if total_market and total_market.present else 1
    for dp_id, label in scope_map.items():
        e = next((x for x in extracted if x.id == dp_id), None)
        if e and e.present and e.value is not None:
            pct = f"{e.value / total_val * 100:.1f}%" if total_val else "-"
            scope_rows.append([label, _fmt(e.value), pct])
    if len(scope_rows) > 1:
        story.append(_mk_table(scope_rows, [7 * cm, 4 * cm, 5.5 * cm], S))
        story.append(Spacer(1, 0.3 * cm))

    # Scope-3-Kategorien
    story.append(Paragraph("Scope-3-Aufschluesslung (materielle Kategorien)", S["h2"]))
    _kpi_table(story, extracted, ["emissions"], S)

    # Intensitaetskennzahl + Bewertung
    story.append(Paragraph("Intensitaetskennzahlen", S["h2"]))
    _kpi_table(story, extracted, ["intensity"], S)
    if assessment:
        ghg_bew = next((b for b in assessment.kpi_bewertungen if b.dp_id == "E1-DP-023"), None)
        if ghg_bew:
            _narrative_box(story, ghg_bew.interpretation, S,
                           bg=_AMPEL_BG.get(ghg_bew.ampel, _GREY_BG))

    story.append(PageBreak())

    # =========================================================================
    # KLIMAZIELE (E1-5) MIT INTERPRETATION
    # =========================================================================
    _section_header(story, "8  Emissionsreduktionsziele (E1-5)", S)

    if assessment:
        _narrative_box(story, sek.get("klimaziele", ""), S)

    _kpi_table(story, extracted, ["targets"], S)

    if assessment:
        red_bew = next((b for b in assessment.kpi_bewertungen if b.dp_id == "E1-DP-021"), None)
        if red_bew:
            _narrative_box(story, red_bew.interpretation, S,
                           bg=_AMPEL_BG.get(red_bew.ampel, _GREY_BG))

    # =========================================================================
    # WEITERE OFFENLEGUNGEN (E1-9/10/11)
    # =========================================================================
    _section_header(story, "9  Weitere Offenlegungen (E1-9 / E1-10 / E1-11)", S)

    if assessment:
        _narrative_box(story, sek.get("nachhaltige_finanzierung", ""), S)

    story.append(Paragraph("THG-Entnahmen und Carbon Credits (E1-9)", S["h2"]))
    _kpi_table(story, extracted, ["removals"], S)

    story.append(Paragraph("Internes Carbon Pricing (E1-10)", S["h2"]))
    _kpi_table(story, extracted, ["carbon_pricing"], S)
    if assessment:
        cp_bew = next((b for b in assessment.kpi_bewertungen if b.dp_id == "E1-DP-026"), None)
        if cp_bew:
            _narrative_box(story, cp_bew.interpretation, S,
                           bg=_AMPEL_BG.get(cp_bew.ampel, _GREY_BG))

    story.append(Paragraph("Antizipierte finanzielle Effekte (E1-11)", S["h2"]))
    _kpi_table(story, extracted, ["financial_effects"], S)
    if assessment:
        risk_bew = next((b for b in assessment.kpi_bewertungen if b.dp_id == "E1-DP-028"), None)
        if risk_bew:
            _narrative_box(story, risk_bew.interpretation, S,
                           bg=_AMPEL_BG.get(risk_bew.ampel, _GREY_BG))

    story.append(PageBreak())

    # =========================================================================
    # ALLE WEITEREN STANDARDS (E2-G1) — WESENTLICH + NICHT WESENTLICH
    # =========================================================================
    section_nr = 10
    if materiality:
        andere_themen = [t for t in materiality.themen if t.standard != "ESRS E1"]
        if andere_themen:
            for t in andere_themen:
                std_prefix = t.id  # z.B. "E2", "S1"
                label = _STANDARD_LABELS.get(std_prefix, t.standard)
                wes_marker = "" if t.wesentlich else " — nicht wesentlich"
                _section_header(story, f"{section_nr}  {label}{wes_marker}", S)
                section_nr += 1

                # Wesentlichkeitsstatus und Begruendung
                if t.wesentlich:
                    status_color = _GREEN
                    status_label = f"WESENTLICH ({t.dimension})"
                else:
                    status_color = colors.grey
                    status_label = "NICHT WESENTLICH"
                story.append(Paragraph(
                    f"Wesentlichkeitsstatus: ",
                    S["body"]
                ))
                story.append(_color_cell(
                    f"{status_label} | Impact-Score: {t.impact_score} | "
                    f"Financial-Score: {t.financial_score} | "
                    f"Schwellenwert: {materiality.schwellenwert}",
                    status_color, S["body"]
                ))
                story.append(Spacer(1, 0.2 * cm))
                story.append(Paragraph(t.begruendung, S["body"]))
                story.append(Spacer(1, 0.2 * cm))

                # Impact-Sub-Kriterien (IG 1 AR 20)
                sk = t.impact_sub_kriterien
                if sk:
                    typ = sk.get("type", "potential")
                    scale = sk.get("scale", "—")
                    scope = sk.get("scope", "—")
                    irrem = sk.get("irremediability", "—")
                    lik = f", Likelihood: {sk['likelihood']}" if "likelihood" in sk else " (actual — keine Likelihood)"
                    sk_rows = [
                        [Paragraph("<b>IG 1 Kriterium</b>", S["cell"]),
                         Paragraph("<b>Wert</b>", S["cell"]),
                         Paragraph("<b>Bedeutung</b>", S["cell"])],
                        ["Scale (Schwere)", str(scale), "Wie gravierend ist die Auswirkung? (1=gering, 5=katastrophal)"],
                        ["Scope (Reichweite)", str(scope), "Wie weit verbreitet ist die Auswirkung? (1=lokal, 5=global)"],
                        ["Irremediability", str(irrem), "Wie schwer ist die Auswirkung rueckgaengig zu machen? (1=leicht, 5=irreversibel)"],
                        ["Typ", typ, "Actual = eingetreten; Potential = koennte eintreten (IG 1 para 44)"],
                    ]
                    if "likelihood" in sk:
                        sk_rows.append(["Likelihood", str(sk["likelihood"]), "Eintrittswahrscheinlichkeit (1=sehr gering, 5=sicher)"])
                    sk_rows.append(["Severity", str(max(float(scale), float(scope), float(irrem))),
                                    "max(Scale, Scope, Irremediability) — IG 1 AR 20"])
                    story.append(Paragraph("Impact-Bewertungsdetails (ESRS 1 IG 1, AR 20)", S["h3"]))
                    story.append(_mk_table(sk_rows, [4 * cm, 2 * cm, 10.5 * cm], S, header=False))
                    story.append(Spacer(1, 0.3 * cm))

                # KPI-Tabelle (immer, auch bei nicht wesentlichen Standards)
                story.append(Paragraph(
                    f"Erhobene Datenpunkte ({t.standard})", S["h2"]
                ))
                if not t.wesentlich:
                    story.append(Paragraph(
                        "Hinweis: Dieser Standard wurde als nicht wesentlich eingestuft. "
                        "Die nachfolgenden Datenpunkte werden zur Vollstaendigkeit und Transparenz "
                        "ausgewiesen, erfordern aber gemaess ESRS 1 Kap. 3.4 keine verpflichtende "
                        "Offenlegung in diesem Bericht.",
                        S["small"]
                    ))
                    story.append(Spacer(1, 0.2 * cm))
                _kpi_table_by_standard(story, extracted, std_prefix, S)
                _narrative_dps(story, extracted, std_prefix, S)

                # Sub-Topics (IG 1 Appendix A)
                if t.sub_topic_bewertungen:
                    story.append(Paragraph(
                        "Sub-Topic-Bewertung (IG 1 Appendix A — zweite Ebene)", S["h2"]
                    ))
                    st_rows = [["Sub-Topic", "Bewertung", "Appendix A Referenz"]]
                    for st in t.sub_topic_bewertungen:
                        if st["status"] == "bewertet":
                            w_text = "wesentlich" if st.get("wesentlich") else "nicht wesentlich"
                            imp = f"Impact: {st['impact_score']}, Financial: {st['financial_score']}"
                            status_text = f"{w_text} ({imp})"
                        else:
                            status_text = "ausstehend — Detailbewertung noch nicht implementiert"
                        st_rows.append([
                            st["name_de"],
                            status_text,
                            st.get("appendix_a_ref", "—"),
                        ])
                    story.append(_mk_table(st_rows, [4.5 * cm, 5 * cm, 7 * cm], S))
                    story.append(Spacer(1, 0.2 * cm))

                story.append(PageBreak())

    # =========================================================================
    # KPI-ASSESSMENT & SEKTORVERGLEICH
    # =========================================================================
    _section_header(story, f"{section_nr}  KPI-Bewertung im Sektorvergleich (ESRS E1)", S)
    section_nr += 1
    story.append(Paragraph(
        "Benchmarks: Synthetisiert aus EBA Pillar 3, BaFin ESG-Berichten und TCFD-Reports "
        "vergleichbarer Finanzinstitute (Bilanzsumme 1-25 Mrd. EUR, Deutschland, 2024).",
        S["small"]
    ))
    story.append(Spacer(1, 0.2 * cm))

    if assessment and assessment.kpi_bewertungen:
        kpi_rows = [["KPI", "Wert", "Einheit", "Sektormedian", "Ampel", "Kurzinterpretation"]]
        for b in assessment.kpi_bewertungen:
            ampel_cell = _color_cell(_AMPEL_LABEL.get(b.ampel, "n/a"),
                                     _AMPEL_COLOR.get(b.ampel, colors.grey), S["cell"])
            kpi_rows.append([
                b.name_de,
                _fmt(b.wert),
                b.einheit,
                _fmt(b.sektor_p50) if b.sektor_p50 else "n/a",
                ampel_cell,
                b.interpretation,
            ])
        story.append(_mk_table(
            kpi_rows, [3.6 * cm, 1.8 * cm, 1.8 * cm, 2.2 * cm, 1.4 * cm, 5.7 * cm], S
        ))
    else:
        story.append(Paragraph("KPI-Bewertung nicht verfuegbar.", S["body"]))

    # =========================================================================
    # HANDLUNGSEMPFEHLUNGEN
    # =========================================================================
    story.append(Spacer(1, 0.5 * cm))
    _section_header(story, f"{section_nr}  Priorisierte Handlungsempfehlungen", S)
    section_nr += 1

    if assessment and assessment.handlungsempfehlungen:
        for i, emp in enumerate(assessment.handlungsempfehlungen, 1):
            if "HOCH" in emp:
                bg = _LIGHT_RED
            elif "MITTEL" in emp:
                bg = _LIGHT_AMBER
            else:
                bg = _GREY_BG
            _narrative_box(story, f"{i}. {emp}", S, bg=bg)
    else:
        story.append(Paragraph("Keine Empfehlungen verfuegbar.", S["body"]))

    story.append(PageBreak())

    # =========================================================================
    # CSRD COMPLIANCE-ERKLAERUNG
    # =========================================================================
    _section_header(story, f"{section_nr}  CSRD/ESRS Compliance-Erklaerung", S)
    section_nr += 1

    # Dynamische Compliance-Tabelle aus Wesentlichkeitsanalyse
    csrd_rows = [["Standard / Anforderung", "Status", "Bemerkung"]]

    # Statische ESRS 1 + 2 Eintraege
    csrd_rows += [
        ["ESRS 1 — Double Materiality Assessment (IRO-1)", "Erfuellt",
         f"Alle 10 Standards bewertet; {len(materiality.wesentliche_themen) if materiality else '?'} wesentlich"],
        ["ESRS 2 — Allgemeine Governance-Angaben", "Partiell (Prototyp)",
         "GOV-1/2, SBM-1/2/3 strukturell abgebildet; narrative Angaben synthetisch"],
    ]

    # Pro Standard dynamisch aus Wesentlichkeitsanalyse
    if materiality:
        for t in materiality.themen:
            dps = [e for e in extracted if e.id.startswith(t.id + "-") and e.present]
            if t.wesentlich:
                status = "Erfuellt"
                bemerkung = f"{len(dps)} Datenpunkte offengelegt; Sub-Topics: IG 1 Appendix A"
            else:
                status = "Nicht berichtspflichtig"
                bemerkung = f"Nicht wesentlich (Impact={t.impact_score}, Financial={t.financial_score}); {len(dps)} DPs zur Transparenz ausgewiesen"
            csrd_rows.append([f"{t.standard} — {t.name_de}", status, bemerkung])

    csrd_rows.append([
        "Vollstaendigkeitsgrad Pflichtdatenpunkte (wesentl. Standards)",
        f"{compliance.completeness_rate * 100:.0f}%",
        f"{compliance.present_mandatory}/{compliance.total_mandatory} Pflichtangaben vorhanden",
    ])

    for r in csrd_rows[1:]:
        if r[1] in ("Erfuellt",):
            r[1] = _color_cell(r[1], _GREEN, S["cell"])
        elif "Partiell" in r[1]:
            r[1] = _color_cell(r[1], _AMBER, S["cell"])
        elif "Nicht berichtspflichtig" in r[1]:
            r[1] = _color_cell(r[1], colors.grey, S["cell"])
        elif "%" in r[1]:
            pct = float(r[1].replace("%", ""))
            r[1] = _color_cell(r[1], _GREEN if pct >= 90 else _AMBER if pct >= 70 else _RED, S["cell"])
    story.append(_mk_table(csrd_rows, [5.5 * cm, 3 * cm, 8 * cm], S))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        "Dieser Bericht wurde automatisiert durch ein KI-Agenten-Framework erstellt "
        "(Weiß, Frankfurt School, 2025/2026). Externe Pruefpflicht nach CSRD Art. 34 bleibt bestehen.",
        S["small"]
    ))

    # =========================================================================
    # EU AI ACT COMPLIANCE-ERKLAERUNG
    # =========================================================================
    story.append(Spacer(1, 0.4 * cm))
    _section_header(story, f"{section_nr}  EU AI Act Transparency-Erklaerung", S)
    section_nr += 1

    story.append(Paragraph(
        "Das KI-Agenten-Framework unterliegt den Transparenz- und Governance-Anforderungen "
        "der EU KI-Verordnung (EU AI Act, 2024/1689). Die nachfolgende Erklaerung dokumentiert "
        "die Konformitaet gemaess den relevanten Artikeln.",
        S["body"]
    ))

    ai_rows = [
        ["Anforderung (EU AI Act)", "Umsetzung", "Status"],
        ["Art. 13: Transparenz und Informationspflichten",
         "Alle KI-generierten Inhalte sind als solche gekennzeichnet. "
         "Modellversion, Konfidenzwerte und Datenherkunft werden dokumentiert.",
         "Erfuellt"],
        ["Art. 14: Menschliche Aufsicht (Human in the Loop)",
         "Konfigurierbarer HITL-Schwellenwert (Standard: 0.75). "
         "Datenpunkte mit Konfidenz < Schwellenwert werden zur manuellen Pruefung markiert.",
         "Erfuellt"],
        ["Art. 15: Genauigkeit, Robustheit, Cybersicherheit",
         "Deterministic Backend: F1=1.0. ML-Klassifikator: CV-F1=0.853 (Seed=42, reproduzierbar). "
         "Vollstaendige Audit-Trail (SHA-256-Hashkette).",
         "Erfuellt"],
        ["Art. 50: Transparenzpflichten fuer KI-Systeme mit begrenztem Risiko",
         "Executive Summary und Narrative als KI-generiert gekennzeichnet. "
         "Nutzer werden explizit auf Pruefpflicht hingewiesen.",
         "Erfuellt"],
        ["Risikoeinstufung",
         "Das System wird als KI-System mit begrenztem Risiko (limited risk) eingestuft. "
         "Es trifft keine autonomen Finanz- oder Kreditentscheidungen; alle Outputs "
         "erfordern menschliche Freigabe.",
         "Limited Risk"],
    ]
    for r in ai_rows[1:]:
        if r[2] == "Erfuellt":
            r[2] = _color_cell(r[2], _GREEN, S["cell"])
        elif r[2] == "Limited Risk":
            r[2] = _color_cell(r[2], _AMBER, S["cell"])
    story.append(_mk_table(ai_rows, [4 * cm, 9 * cm, 2.5 * cm], S))
    story.append(PageBreak())

    # =========================================================================
    # VALIDIERUNGSERGEBNISSE
    # =========================================================================
    _section_header(story, f"{section_nr}  Validierungsergebnisse", S)
    section_nr += 1
    crit_count = sum(1 for i in validation_issues if i.severity == "critical")
    story.append(Paragraph(
        f"Gesamt: {len(validation_issues)} Issues | Kritisch: {crit_count} | "
        f"Pruefregeln: catalog_bounds, sum_equals, derived_equals, relation, non_negative, range",
        S["body"]
    ))
    if validation_issues:
        vrows = [["Pruefung", "Schwere", "Pfad", "Meldung"]]
        for issue in validation_issues:
            c = {"critical": _RED, "warning": _AMBER}.get(issue.severity, colors.black)
            vrows.append([
                issue.check,
                _color_cell(issue.severity, c, S["cell"]),
                issue.path,
                issue.message,
            ])
        story.append(_mk_table(vrows, [3 * cm, 2 * cm, 4 * cm, 7.5 * cm], S))
    else:
        story.append(Paragraph("Keine Validierungsfehler. Alle Plausibilitaetspruefungen bestanden.", S["body"]))

    if compliance.gaps:
        story.append(Paragraph("Compliance-Luecken (fehlende Pflichtdatenpunkte):", S["h2"]))
        gaprows = [["Datenpunkt-ID", "DR", "Bezeichnung"]]
        for g in compliance.gaps:
            gaprows.append([g.get("id", "-"), g.get("dr", "-"), g.get("name_de", "-")])
        story.append(_mk_table(gaprows, [3.5 * cm, 2.5 * cm, 10.5 * cm], S))

    # =========================================================================
    # DATENHERKUNFT (PROVENANCE)
    # =========================================================================
    _section_header(story, f"{section_nr}  Datenherkunft und Konfidenz (Provenance)", S)
    story.append(Paragraph(
        "Gemaess FA-1.4 und NFA-1.1 wird fuer jeden Datenpunkt die Quellenherkunft, "
        "die Extraktionsmethode und der Konfidenzwert dokumentiert.",
        S["small"]
    ))
    story.append(Spacer(1, 0.2 * cm))
    prows = [["ID", "Name", "Methode", "Konfidenz", "Status"]]
    for e in extracted:
        status = (_color_cell("OK", _GREEN, S["cell"]) if e.present
                  else _color_cell("FEHLT", _RED, S["cell"]))
        prows.append([
            e.id, e.name_de,
            e.source.get("method", "-"),
            f"{e.confidence:.2f}",
            status,
        ])
    story.append(_mk_table(prows, [2.5 * cm, 6.5 * cm, 3 * cm, 1.8 * cm, 2.7 * cm], S))

    # Footer-Hinweis
    story.append(Spacer(1, 0.5 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_GREY_LINE))
    story.append(Paragraph(
        f"Erstellt: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | "
        f"Framework: KI-Agenten ESG v1.0 (Weiß, Frankfurt School, 2025/2026) | "
        f"Backend: {backend} | Laufzeit: {elapsed_seconds}s | "
        f"Rahmen: CSRD / ESRS E1-G1 (Amended Exposure Drafts, Juli 2025) / EU AI Act 2024/1689",
        S["small"]
    ))

    doc.build(story)
    return buf.getvalue()


def save_pdf(path: str | Path, *args, **kwargs) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(build_pdf_bytes(*args, **kwargs))
    return target
